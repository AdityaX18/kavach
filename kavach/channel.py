"""Telephone-channel simulator: turn clean audio into what a phone line delivers.

  clean        16 kHz, untouched
  phone        8 kHz, 300-3400 Hz band-pass, 8-bit mu-law (G.711-style) companding
  phone_noisy  phone + pink noise at 10 dB SNR (a busy street / shop)

Honest limits: no packet loss, no codec switching, no real PSTN echo. Mu-law here is the
continuous companding curve with 8-bit quantisation, a close approximation of G.711's
segmented table. Real calls should be recorded to validate (see README).
"""

from __future__ import annotations

import io
from math import gcd

import numpy as np
import soundfile as sf
from scipy.signal import butter, resample_poly, sosfiltfilt

CONDITIONS = {
    "clean": None,
    "phone": {"snr_db": None},
    "phone_noisy": {"snr_db": 10.0},
}


def read_wav(data: bytes) -> tuple[np.ndarray, int]:
    x, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=False)
    if x.ndim > 1:
        x = x.mean(axis=1)
    return x.astype(np.float32), int(sr)


def write_wav(x: np.ndarray, sr: int) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, np.clip(x, -1.0, 1.0), sr, subtype="PCM_16", format="WAV")
    return buf.getvalue()


def _mulaw(x: np.ndarray, mu: float = 255.0) -> np.ndarray:
    """Compress, quantise to 8 bits, expand."""
    y = np.sign(x) * np.log1p(mu * np.abs(x)) / np.log1p(mu)
    q = np.round((y + 1.0) / 2.0 * 255.0)
    y2 = q / 255.0 * 2.0 - 1.0
    return np.sign(y2) * (np.power(1.0 + mu, np.abs(y2)) - 1.0) / mu


def pink_noise(n: int, rng: np.random.Generator) -> np.ndarray:
    white = rng.standard_normal(n)
    spec = np.fft.rfft(white)
    f = np.fft.rfftfreq(n)
    f[0] = f[1] if n > 1 else 1.0
    pink = np.fft.irfft(spec / np.sqrt(f), n)
    return pink / (np.std(pink) + 1e-12)


def _speech_rms(x: np.ndarray, sr: int) -> float:
    """RMS over active frames only (frames within 30 dB of the loudest), so pauses don't skew SNR."""
    frame = max(1, int(0.02 * sr))
    n = len(x) // frame
    if n == 0:
        return float(np.sqrt(np.mean(x**2) + 1e-12))
    e = (x[: n * frame].reshape(n, frame) ** 2).mean(axis=1)
    active = e[e > e.max() * 1e-3]
    return float(np.sqrt(active.mean() + 1e-12))


def telephone(x: np.ndarray, sr: int, snr_db: float | None = None, seed: int = 0) -> tuple[np.ndarray, int]:
    g = gcd(8000, sr)
    y = resample_poly(x, 8000 // g, sr // g) if sr != 8000 else x.copy()
    sos = butter(4, [300, 3400], btype="bandpass", fs=8000, output="sos")
    y = sosfiltfilt(sos, y)
    if snr_db is not None:
        rng = np.random.default_rng(seed)
        noise = sosfiltfilt(sos, pink_noise(len(y), rng))
        target = _speech_rms(y, 8000) / (10 ** (snr_db / 20))
        y = y + noise / (np.sqrt(np.mean(noise**2)) + 1e-12) * target
    peak = np.max(np.abs(y)) + 1e-12
    if peak > 0.99:
        y = y / peak * 0.99
    return _mulaw(y).astype(np.float32), 8000


def apply_condition(wav: bytes, condition: str, seed: int = 0) -> bytes:
    if condition not in CONDITIONS:
        raise ValueError(f"unknown condition {condition!r}; use one of {list(CONDITIONS)}")
    spec = CONDITIONS[condition]
    if spec is None:
        return wav
    x, sr = read_wav(wav)
    y, sr2 = telephone(x, sr, snr_db=spec["snr_db"], seed=seed)
    return write_wav(y, sr2)
