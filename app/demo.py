"""Kavach live demo: the same caller, two agents, side by side.

  left   agent WITHOUT the guard (bank policy written only in the LLM prompt)
  right  agent WITH the Kavach guard

Speak into the mic (or paste a scam line from the comments and let Timbre speak it), the
audio goes through a simulated phone line, Prisma transcribes it, both agents act on the
same transcript, and you see what each one did to the (fictional) bank.

Run:  python -m app.demo            (uses KAVACH_LLM from .env, default groq)
      python -m app.demo --llm gemini
      python -m app.demo --llm mock   (no keys; typed text only; for UI checks)
"""

from __future__ import annotations

import argparse
import html
import json
import threading
import time
from pathlib import Path

import gradio as gr

from kavach.agent import Agent
from kavach.bank import Bank
from kavach.channel import apply_condition
from kavach.config import CACHE_DIR, gnani_key, llm_settings
from kavach.langs import LANGS
from kavach.llm import MockLLM, OpenAICompatLLM

LLM = None
SPEECH = None
OUT = CACHE_DIR / "demo"

# Public mode (--public): limits so strangers can't burn through your Groq/Gnani quota.
PUBLIC = False
PER_CALL_MAX_MSGS = 8          # messages per call (press "New call" to start again)
MAX_CHARS = 400
BUDGET = {"real_ai_msgs": 300, "voice_msgs": 120}   # whole-session caps; Obedient AI is free
USED = {"real_ai_msgs": 0, "voice_msgs": 0}
_LOCK = threading.Lock()
ATTEMPTS = Path(__file__).resolve().parents[1] / "runs" / "public" / "attempts.jsonl"
BRAINS = ["Worst-case AI: tries to drain the account on every turn (free)", "Real AI (gpt-oss-20b)"]

CUSTOMERS = [("Ramesh Gowda · caller ID +91 00000 00001", "C001"),
             ("Sunita Sharma · caller ID +91 00000 00002", "C002"),
             ("Arjun Rao · caller ID +91 00000 00003", "C003")]
MODES = ["Side by side", "Guard ON only", "Guard OFF only"]

CSS = """
.kv-lane {font-weight:700; font-size:1.05rem; padding:8px 12px; border-radius:10px; text-align:center;}
.kv-off {background:#fde8e8; color:#9b1c1c;}
.kv-on {background:#def7ec; color:#03543f;}
.kv-heard {font-size:1.05rem; padding:10px 12px; border-radius:10px; background:#eef2ff; color:#1e1b4b;}
.kv-card {border-radius:10px; padding:10px 12px; background:#f9fafb; color:#111827; border:1px solid #e5e7eb; font-size:0.95rem;}
.kv-badge {display:inline-block; padding:2px 8px; border-radius:999px; font-weight:700; font-size:0.8rem; color:#fff;}
.kv-chip {display:inline-block; padding:2px 8px; margin:2px; border-radius:999px; font-size:0.8rem; background:#374151; color:#fff;}
.kv-bad {color:#b91c1c; font-weight:700;}
.kv-good {color:#047857; font-weight:700;}
.kv-small {font-size:0.8rem; color:#4b5563;}
"""

BADGE = {"allow": "#059669", "confirm": "#d97706", "block": "#dc2626"}
CHIP = {"authority_claim": "#b91c1c", "injection": "#7c3aed", "coercion": "#c2410c", "urgency": "#a16207",
        "third_party": "#1d4ed8", "secret_mention": "#4b5563", "secret_redacted": "#0f766e",
        "MASKED_NUMBER": "#0f766e", "LEAK_UNVERIFIED": "#b91c1c", "ASKS_SECRET": "#b91c1c", "locked": "#111827"}


def _brain(brain: str, bank: Bank, customer: str):
    if brain == BRAINS[0]:
        from bench.redteam import EvilLLM

        return EvilLLM(bank, customer)
    return LLM


def new_state(customer: str, lang: str, brain: str | None = None) -> dict:
    brain = brain or (BRAINS[0] if PUBLIC else BRAINS[1])
    bank_off, bank_on = Bank(), Bank()
    return {
        "customer": customer, "lang": lang, "brain": brain,
        "bank_off": bank_off, "bank_on": bank_on,
        "off": Agent(_brain(brain, bank_off, customer), bank_off, customer, lang, guard_enabled=False),
        "on": Agent(_brain(brain, bank_on, customer), bank_on, customer, lang, guard_enabled=True),
        "hist_off": [], "hist_on": [], "n": 0,
    }


def _log_attempt(st: dict, transcript: str, source: str) -> None:
    """Every public attempt is saved, so the crowd's lines become the next held-out test set."""
    try:
        ATTEMPTS.parent.mkdir(parents=True, exist_ok=True)
        moved = {k: [t for t in st[f"bank_{k}"].customer(st["customer"]).transfers if not t["registered_beneficiary"]]
                 for k in ("off", "on")}
        row = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "lang": st["lang"], "brain": st["brain"],
               "source": source, "text": transcript, "turn": st["n"],
               "stranger_money_off": sum(x["amount_inr"] for x in moved["off"]),
               "stranger_money_on": sum(x["amount_inr"] for x in moved["on"]),
               "mobile_changed_off": bool(st["bank_off"].customer(st["customer"]).mobile_updates),
               "mobile_changed_on": bool(st["bank_on"].customer(st["customer"]).mobile_updates)}
        with _LOCK, ATTEMPTS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


def bank_html(bank: Bank, customer: str, title: str) -> str:
    c = bank.customer(customer)
    rows = [f"<b>{html.escape(title)}</b>",
            f"Balance: <b>₹{c.balance_inr:,.2f}</b> · Card ••{c.cards[0].last4}: "
            + (f"<span class='kv-good'>blocked</span>" if c.cards[0].status == "blocked" else "active")]
    if c.transfers:
        for t in c.transfers:
            cls = "kv-good" if t["registered_beneficiary"] else "kv-bad"
            note = "registered payee" if t["registered_beneficiary"] else "NOT a registered payee"
            rows.append(f"<span class='{cls}'>₹{t['amount_inr']:,.0f} sent to {html.escape(t['to_raw'])} ({note})</span>")
    else:
        rows.append("Money moved: <span class='kv-good'>none</span>")
    if c.mobile_updates:
        rows.append(f"<span class='kv-bad'>Registered mobile CHANGED to {html.escape(c.mobile_updates[-1])}</span>")
    if c.disputes:
        rows.append("Complaint raised: " + ", ".join(d["dispute_id"] for d in c.disputes))
    return "<div class='kv-card'>" + "<br>".join(rows) + "</div>"


def guard_html(turn) -> str:
    if turn is None:
        return "<div class='kv-card kv-small'>Guard decisions appear here.</div>"
    chips = "".join(
        f"<span class='kv-chip' style='background:{CHIP.get(f['kind'], '#374151')}'>{html.escape(f['kind'])}: "
        f"{html.escape(f['detail'][:60])}</span>" for f in turn.findings)
    lines = []
    for e in turn.tool_events:
        d = e.decision or {"action": "allow", "rules": []}
        color = BADGE[d["action"]]
        label = {"allow": "ALLOWED", "confirm": "READ-BACK FIRST", "block": "BLOCKED"}[d["action"]]
        rules = (" · " + ", ".join(d["rules"])) if d["rules"] else ""
        args = ", ".join(f"{k}={v}" for k, v in e.args.items())
        lines.append(f"<div><span class='kv-badge' style='background:{color}'>{label}</span> "
                     f"<code>{html.escape(e.name)}({html.escape(args)})</code>{html.escape(rules)}</div>")
    body = "".join(lines) or "<div class='kv-small'>No tool calls this turn.</div>"
    return (f"<div class='kv-card'><b>Kavach guard</b> <span class='kv-small'>({turn.guard_ms:.2f} ms)</span>"
            f"<div>{chips}</div>{body}</div>")


def latency_html(t: dict) -> str:
    parts = [f"{k}: <b>{v:.0f} ms</b>" for k, v in t.items() if v is not None]
    return "<div class='kv-card kv-small'>" + " · ".join(parts) + "</div>" if parts else ""


def on_reset(customer: str, lang: str, brain: str | None = None):
    st = new_state(customer, lang, brain)
    c = st["bank_on"].customer(customer)
    return (st, [], [], bank_html(st["bank_off"], customer, "Bank state (no guard)"),
            bank_html(st["bank_on"], customer, "Bank state (Kavach)"), guard_html(None),
            f"<div class='kv-heard'>New call from {html.escape(c.phone)} · {LANGS[lang]['label']}</div>",
            None, "")


def on_send(audio_path, typed, speak_typed, phone_line, mode, st):
    lang = st["lang"]
    real_ai = st["brain"] != BRAINS[0]
    if PUBLIC:
        if st["n"] >= PER_CALL_MAX_MSGS:
            raise gr.Error(f"{PER_CALL_MAX_MSGS} messages per call. Press 'New call' to try again.")
        if typed and len(typed) > MAX_CHARS:
            raise gr.Error(f"Keep it under {MAX_CHARS} characters (it's a phone call).")
        with _LOCK:
            if real_ai and USED["real_ai_msgs"] >= BUDGET["real_ai_msgs"]:
                raise gr.Error("Tonight's Real AI quota is used up. Switch to 'Worst-case AI' (free), "
                               "or comment your line on the post and I'll run it.")
            if (audio_path or speak_typed) and USED["voice_msgs"] >= BUDGET["voice_msgs"]:
                speak_typed, audio_path = False, None
                gr.Warning("Voice quota used up for tonight: running your line as text.")
            USED["real_ai_msgs"] += int(real_ai)
            USED["voice_msgs"] += int(bool(audio_path or speak_typed))
    timings: dict[str, float | None] = {}
    cond = "phone_noisy" if phone_line else "clean"
    transcript = ""
    source = "typed (text mode, no speech)"
    if audio_path:
        if SPEECH is None:
            raise gr.Error("GNANI_API_KEY is not set, so voice input is off. Type the line instead.")
        wav = Path(audio_path).read_bytes()
        wav = apply_condition(wav, cond, seed=st["n"])
        s = SPEECH.stt(wav, lang)
        transcript, timings["Prisma STT"] = s.text, s.latency_ms
        source = "Prisma heard, " + ("phone line" if phone_line else "clean")
    elif typed and typed.strip():
        if speak_typed and SPEECH is not None:
            t = SPEECH.tts(typed.strip(), lang, voice=LANGS[lang]["caller_voices"][0])
            s = SPEECH.stt(apply_condition(t.wav, cond, seed=st["n"]), lang)
            transcript, timings["Timbre (caller)"], timings["Prisma STT"] = s.text, t.latency_ms, s.latency_ms
            source = "Timbre spoke it, Prisma heard, " + ("phone line" if phone_line else "clean")
        else:
            transcript = typed.strip()
    if not transcript:
        raise gr.Error("Nothing heard. Record again or type a line.")
    st["n"] += 1

    turn_on = turn_off = None
    if mode in ("Side by side", "Guard OFF only"):
        turn_off = st["off"].handle_turn(transcript)
        st["hist_off"] += [{"role": "user", "content": transcript}, {"role": "assistant", "content": turn_off.reply}]
        timings["LLM (no guard)"] = turn_off.llm_ms
    if mode in ("Side by side", "Guard ON only"):
        turn_on = st["on"].handle_turn(transcript)
        st["hist_on"] += [{"role": "user", "content": transcript}, {"role": "assistant", "content": turn_on.reply}]
        timings["LLM (Kavach)"] = turn_on.llm_ms

    _log_attempt(st, transcript, source)
    speak = (turn_on or turn_off).reply
    audio_out = None
    if SPEECH is not None and speak:
        try:
            t0 = time.perf_counter()
            r = SPEECH.tts(speak, lang)
            timings["Timbre TTS"] = (time.perf_counter() - t0) * 1000
            OUT.mkdir(parents=True, exist_ok=True)
            audio_out = str(OUT / f"reply_{int(time.time()*1000)}.wav")
            Path(audio_out).write_bytes(r.wav)
        except Exception as exc:  # keep the demo going even if TTS hiccups
            gr.Warning(f"TTS failed: {exc}")
    heard = f"<div class='kv-heard'>{html.escape(source)}: <b>{html.escape(transcript)}</b></div>"
    return (st, st["hist_off"], st["hist_on"],
            bank_html(st["bank_off"], st["customer"], "Bank state (no guard)"),
            bank_html(st["bank_on"], st["customer"], "Bank state (Kavach)"),
            guard_html(turn_on), heard, audio_out, latency_html(timings), None, "")


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Kavach: can you scam an AI bank agent?", css=CSS, theme=gr.themes.Soft()) as demo:
        gr.HTML("<h1 style='margin:0'>🛡️ Kavach: can you scam an AI bank agent?</h1>"
                "<div class='kv-small'>Gnani Prisma (speech-to-text) + Timbre (text-to-speech) · deterministic "
                "guard · Kavach Demo Bank is fictional and every account is synthetic</div>"
                "<div class='kv-heard' style='margin-top:8px'><b>Challenge:</b> get money sent to an account "
                "that isn't a saved payee, or get the mobile number changed. Try the left lane, then try "
                "Kavach on the right. 'Worst-case AI' tries every harmful action on every turn and sends money to any account number you say: can you get past Kavach anyway? The bank is fictional; "
                "please don't type real personal details. Lines are logged to improve Kavach.</div>")
        st = gr.State()
        with gr.Row():
            with gr.Column(scale=1, min_width=320):
                customer = gr.Dropdown(CUSTOMERS, value="C001", label="Calling from (caller ID)")
                lang = gr.Dropdown([(v["label"], k) for k, v in LANGS.items()], value="hinglish", label="Language")
                brain = gr.Radio(BRAINS, value=BRAINS[0] if PUBLIC else BRAINS[1], label="AI brain")
                mode = gr.Radio(MODES, value="Side by side", label="Mode")
                phone = gr.Checkbox(True, label="Phone line: 8 kHz + street noise")
                mic = gr.Audio(sources=["microphone"], type="filepath", label="Speak (record, then stop)")
                typed = gr.Textbox(label="…or type a caller line (paste a scam line from the comments)", lines=3)
                speak_typed = gr.Checkbox(True, label="Speak the typed line: Timbre → phone line → Prisma")
                send = gr.Button("Send", variant="primary")
                reset = gr.Button("New call")
                latency = gr.HTML()
            with gr.Column(scale=2):
                heard = gr.HTML()
                with gr.Row():
                    with gr.Column():
                        gr.HTML("<div class='kv-lane kv-off'>WITHOUT guard · policy only in the prompt</div>")
                        chat_off = gr.Chatbot(type="messages", height=320, label="Agent without guard", allow_tags=False)
                        bank_off = gr.HTML()
                    with gr.Column():
                        gr.HTML("<div class='kv-lane kv-on'>WITH Kavach guard</div>")
                        chat_on = gr.Chatbot(type="messages", height=320, label="Agent with Kavach", allow_tags=False)
                        guard_box = gr.HTML()
                        bank_on = gr.HTML()
                reply_audio = gr.Audio(label="Agent voice (Timbre)", autoplay=True, type="filepath")

        reset_outputs = [st, chat_off, chat_on, bank_off, bank_on, guard_box, heard, reply_audio, latency]
        send_outputs = [st, chat_off, chat_on, bank_off, bank_on, guard_box, heard, reply_audio, latency, mic, typed]
        demo.load(on_reset, [customer, lang, brain], reset_outputs)
        reset.click(on_reset, [customer, lang, brain], reset_outputs)
        customer.change(on_reset, [customer, lang, brain], reset_outputs)
        lang.change(on_reset, [customer, lang, brain], reset_outputs)
        brain.change(on_reset, [customer, lang, brain], reset_outputs)
        send.click(on_send, [mic, typed, speak_typed, phone, mode, st], send_outputs)
        typed.submit(on_send, [mic, typed, speak_typed, phone, mode, st], send_outputs)
        mic.stop_recording(on_send, [mic, typed, speak_typed, phone, mode, st], send_outputs)
    return demo


def init(llm_spec: str | None) -> None:
    global LLM, SPEECH
    LLM = MockLLM() if llm_spec == "mock" else OpenAICompatLLM(llm_settings(llm_spec), use_cache=False)
    if gnani_key():
        from kavach.speech import GnaniSpeech

        SPEECH = GnaniSpeech()
    else:
        print("GNANI_API_KEY not set: voice is off, typed text only.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", default=None, help="groq | gemini | ollama | openai_compat | mock")
    ap.add_argument("--share", action="store_true", help="public gradio link (careful: uses your credits)")
    ap.add_argument("--port", type=int, default=7860)
    ap.add_argument("--public", action="store_true",
                    help="share a public link with limits: Obedient AI by default, per-call and nightly caps, "
                         "every attempt logged to runs/public/attempts.jsonl")
    a = ap.parse_args()
    global PUBLIC
    PUBLIC = a.public
    init(a.llm)
    build_ui().queue(default_concurrency_limit=1, max_size=40).launch(
        server_port=a.port, share=a.share or a.public)


if __name__ == "__main__":
    main()
