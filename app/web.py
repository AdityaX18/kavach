"""Kavach live demo, hand-built page (replaces the Gradio UI for recording and sharing).

  python -m app.web --llm groq:openai/gpt-oss-20b          # http://127.0.0.1:7860
  python -m app.web --llm mock                              # no keys, typed only

The browser records the mic itself (Web Audio -> 16 kHz WAV), so no Gradio audio widget is involved.
Same backend as app/demo.py: same agents, same guard, same Gnani calls, same attempt log.
"""

from __future__ import annotations

import argparse
import base64
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from app import demo as D
from kavach.channel import apply_condition
from kavach.langs import LANGS

HERE = Path(__file__).resolve().parent
SESSIONS: dict[str, dict] = {}
SPEECH_LOCK = threading.Lock()   # Gnani allows one active request per account
app = FastAPI()


class TurnIn(BaseModel):
    sid: str
    customer: str = "C001"
    lang: str = "hinglish"
    brain: str = "real"          # "real" | "worst"
    mode: str = "both"           # "both" | "on" | "off"
    phone: bool = True
    speak: bool = True
    text: str = ""
    audio_b64: str = ""


class ResetIn(BaseModel):
    sid: str
    customer: str = "C001"
    lang: str = "hinglish"
    brain: str = "real"


def _brain_name(b: str) -> str:
    return D.BRAINS[0] if b == "worst" else D.BRAINS[1]


def _session(sid: str, customer: str, lang: str, brain: str, fresh: bool = False) -> dict:
    st = SESSIONS.get(sid)
    if fresh or st is None or st["customer"] != customer or st["lang"] != lang or st["brain"] != _brain_name(brain):
        st = D.new_state(customer, lang, _brain_name(brain))
        st["lock"] = threading.Lock()
        SESSIONS[sid] = st
    return st


def _ledger(bank, customer: str) -> dict:
    c = bank.customer(customer)
    return {
        "balance": c.balance_inr,
        "card": {"last4": c.cards[0].last4, "status": c.cards[0].status},
        "transfers": [{"to": t["to_raw"], "amount": t["amount_inr"], "saved_payee": t["registered_beneficiary"]}
                      for t in c.transfers],
        "mobile_changed": c.mobile_updates[-1] if c.mobile_updates else None,
        "disputes": [d["dispute_id"] for d in c.disputes],
    }


def _lane(turn, bank, customer: str) -> dict | None:
    if turn is None:
        return None
    tools = []
    for e in turn.tool_events:
        d = e.decision or {"action": "allow", "rules": []}
        tools.append({"name": e.name, "args": e.args, "action": d["action"], "rules": d.get("rules", [])})
    return {"reply": turn.reply, "tools": tools, "findings": turn.findings,
            "guard_ms": round(turn.guard_ms, 2), "llm_ms": round(turn.llm_ms), "ledger": _ledger(bank, customer)}


@app.get("/", response_class=HTMLResponse)
def index():
    return (HERE / "web" / "index.html").read_text(encoding="utf-8")


@app.get("/audio/{name}")
def audio(name: str):
    p = D.OUT / Path(name).name
    return FileResponse(p, media_type="audio/wav") if p.exists() else JSONResponse({"error": "gone"}, 404)


@app.post("/api/reset")
def reset(r: ResetIn):
    st = _session(r.sid, r.customer, r.lang, r.brain, fresh=True)
    c = st["bank_on"].customer(r.customer)
    return {"caller": c.name, "phone": c.phone, "payees": [b.key if hasattr(b, "key") else str(b) for b in c.beneficiaries],
            "ledger_off": _ledger(st["bank_off"], r.customer), "ledger_on": _ledger(st["bank_on"], r.customer),
            "voice": D.SPEECH is not None}


@app.post("/api/turn")
def turn(r: TurnIn):
    try:
        return _turn(r)
    except Exception as exc:  # always answer, so the page never hangs
        return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, 500)


def _turn(r: TurnIn) -> dict:
    st = _session(r.sid, r.customer, r.lang, r.brain)
    lang, cond = r.lang, ("phone_noisy" if r.phone else "clean")
    timings: dict[str, float] = {}
    transcript, source = "", "typed"
    with st["lock"]:
        if r.audio_b64:
            if D.SPEECH is None:
                return {"error": "Voice is off (no GNANI_API_KEY). Type the line instead."}
            wav = base64.b64decode(r.audio_b64)
            with SPEECH_LOCK:
                s = D.SPEECH.stt(apply_condition(wav, cond, seed=st["n"]), lang, filename="mic.wav")
            transcript, timings["Prisma STT"] = s.text, s.latency_ms
            source = "Prisma heard your voice" + (" over a phone line" if r.phone else "")
        elif r.text.strip():
            text = r.text.strip()[:600]
            if r.speak and D.SPEECH is not None:
                with SPEECH_LOCK:
                    t = D.SPEECH.tts(text, lang, voice=LANGS[lang]["caller_voices"][0])
                    s = D.SPEECH.stt(apply_condition(t.wav, cond, seed=st["n"]), lang)
                transcript = s.text
                timings["Timbre (caller)"], timings["Prisma STT"] = t.latency_ms, s.latency_ms
                source = "Timbre spoke it, Prisma heard it" + (" over a phone line" if r.phone else "")
            else:
                transcript = text
        if not transcript:
            return {"error": "Nothing was heard. Hold the mic a little longer, or type the line."}
        st["n"] += 1
        t_off = t_on = None
        if r.mode in ("both", "off"):
            t_off = st["off"].handle_turn(transcript)
        if r.mode in ("both", "on"):
            t_on = st["on"].handle_turn(transcript)
        D._log_attempt(st, transcript, source)
        audio_url = None
        speak = (t_on or t_off).reply
        if D.SPEECH is not None and speak:
            try:
                with SPEECH_LOCK:
                    t0 = time.perf_counter()
                    out = D.SPEECH.tts(speak, lang)
                    timings["Timbre (agent)"] = (time.perf_counter() - t0) * 1000
                D.OUT.mkdir(parents=True, exist_ok=True)
                name = f"reply_{int(time.time() * 1000)}.wav"
                (D.OUT / name).write_bytes(out.wav)
                audio_url = f"/audio/{name}"
            except Exception:
                pass
        return {"heard": transcript, "source": source, "timings": {k: round(v) for k, v in timings.items() if v},
                "off": _lane(t_off, st["bank_off"], st["customer"]), "on": _lane(t_on, st["bank_on"], st["customer"]),
                "audio": audio_url}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", default=None)
    ap.add_argument("--port", type=int, default=7860)
    a = ap.parse_args()
    D.init(a.llm)
    print(f"Kavach demo: http://127.0.0.1:{a.port}")
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
