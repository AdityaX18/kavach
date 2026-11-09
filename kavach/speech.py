"""Speech in and out, through Gnani's official SDK (gnani-vachana).

  STT: Prisma  REST  POST https://api.vachana.ai/stt/v3        (audio up to 30 s)
  TTS: Timbre  REST  POST https://api.vachana.ai/api/v1/tts/inference

Both are cached on disk by content hash, so the benchmark never pays twice for the same
audio, and a crashed run resumes for free. Latency is measured around each real call.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .config import CACHE_DIR, STT_MODEL, TTS_MODEL, gnani_key
from .langs import LANGS

logging.getLogger("gnani").setLevel(logging.WARNING)  # the SDK logs every request at INFO


@dataclass
class STTResult:
    text: str
    latency_ms: float
    cached: bool
    meta: dict = field(default_factory=dict)


@dataclass
class TTSResult:
    wav: bytes
    latency_ms: float
    cached: bool


def _with_backoff(fn, *args, **kwargs):
    """Gnani allows one active request per account: retry 429s with exponential backoff."""
    delay = 1.0
    for attempt in range(7):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            code = getattr(exc, "status_code", None)
            if code == 402:
                raise RuntimeError("Gnani credits exhausted (HTTP 402).") from exc
            if code == 429 and attempt < 6:
                time.sleep(delay)
                delay = min(delay * 2, 20.0)
                continue
            raise


def _h(*parts: bytes | str) -> str:
    m = hashlib.sha256()
    for p in parts:
        m.update(p if isinstance(p, bytes) else p.encode())
        m.update(b"\x00")
    return m.hexdigest()


class GnaniSpeech:
    label = "gnani"

    def __init__(self, api_key: str | None = None, stt_model: str | None = STT_MODEL,
                 tts_model: str = TTS_MODEL, use_cache: bool = True, cache_dir: Path | None = None):
        from gnani.stt import GnaniSTTClient
        from gnani.tts import GnaniTTSClient

        # The SDK resets its logger to DEBUG when it is first imported (just above), so silence it
        # here, not at module load. 429s are retried by _with_backoff; real failures still raise.
        logging.getLogger("gnani").setLevel(logging.CRITICAL)

        key = api_key or gnani_key()
        if not key:
            raise ValueError("GNANI_API_KEY is not set. Add it to .env (see .env.example).")
        self.stt_client = GnaniSTTClient(api_key=key, timeout=60)
        self.tts_client = GnaniTTSClient(api_key=key, timeout=60)
        self.stt_model = stt_model
        self.tts_model = tts_model
        self.use_cache = use_cache
        root = cache_dir or CACHE_DIR
        self.stt_dir = root / "stt"
        self.tts_dir = root / "tts"
        self.stt_dir.mkdir(parents=True, exist_ok=True)
        self.tts_dir.mkdir(parents=True, exist_ok=True)
        self.calls = {"stt": 0, "tts": 0}  # real (non-cached) API calls this process

    # ------------------------------------------------------------------ TTS
    def tts(self, text: str, lang: str, voice: str | None = None, sample_rate: int = 16000) -> TTSResult:
        from gnani.tts import AudioConfig

        cfg = LANGS[lang]
        voice = voice or cfg["agent_voice"]
        key = _h("tts", self.tts_model, voice, str(cfg["tts_lang"]), str(sample_rate), text)
        path = self.tts_dir / f"{key}.wav"
        if self.use_cache and path.exists():
            return TTSResult(path.read_bytes(), 0.0, True)
        t0 = time.perf_counter()
        audio = _with_backoff(
            self.tts_client.synthesize,
            text,
            voice=voice,
            model=self.tts_model,
            language=cfg["tts_lang"],
            audio_config=AudioConfig(sample_rate=sample_rate, encoding="linear_pcm", container="wav"),
        )
        latency = (time.perf_counter() - t0) * 1000
        self.calls["tts"] += 1
        if self.use_cache:
            path.write_bytes(audio)
        return TTSResult(audio, latency, False)

    # ------------------------------------------------------------------ STT
    def stt(self, wav: bytes, lang: str, filename: str = "audio.wav", **_hints) -> STTResult:
        cfg = LANGS[lang]
        key = _h("stt", str(self.stt_model), cfg["stt_lang"], cfg["stt_format"], wav)
        path = self.stt_dir / f"{key}.json"
        if self.use_cache and path.exists():
            d = json.loads(path.read_text())
            return STTResult(d["text"], d["latency_ms"], True, d.get("meta", {}))
        t0 = time.perf_counter()
        resp = _with_backoff(
            self.stt_client.transcribe_bytes,
            wav, filename=filename, language_code=cfg["stt_lang"],
            model=self.stt_model, format=cfg["stt_format"],
        )
        latency = (time.perf_counter() - t0) * 1000
        self.calls["stt"] += 1
        text = (resp.get("transcript") or "").strip()
        meta = {k: resp.get(k) for k in ("model", "processing_time", "end_to_end_latency",
                                          "detected_language_code", "truncated", "request_id") if k in resp}
        if self.use_cache:
            path.write_text(json.dumps({"text": text, "latency_ms": latency, "meta": meta}, ensure_ascii=False))
        return STTResult(text, latency, False, meta)


class MockSpeech:
    """Offline stand-in for tests. TTS makes a tone; STT returns the reference text, lightly
    corrupted on 'phone' conditions so the plumbing for WER and ASR-induced failures is exercised.
    Never report numbers from this class."""

    label = "mock"

    def __init__(self) -> None:
        self.calls = {"stt": 0, "tts": 0}

    def tts(self, text: str, lang: str, voice: str | None = None, sample_rate: int = 16000) -> TTSResult:
        dur = min(8.0, 0.4 + 0.06 * len(text))
        t = np.arange(int(sample_rate * dur)) / sample_rate
        x = 0.2 * np.sin(2 * np.pi * 220 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 3 * t))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sample_rate)
            w.writeframes((x * 32767).astype("<i2").tobytes())
        return TTSResult(buf.getvalue(), 1.0, False)

    def stt(self, wav: bytes, lang: str, ref_text: str = "", condition: str = "clean", **_hints) -> STTResult:
        words = ref_text.split()
        if condition.startswith("phone") and len(words) > 6:
            # deterministic 'error': drop every 9th word on phone audio
            words = [w for i, w in enumerate(words) if (i + 1) % 9]
        return STTResult(" ".join(words), 1.0, False, {"mock": True})
