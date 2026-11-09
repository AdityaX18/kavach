"""Command line.

  python -m kavach.cli smoke              # check keys, latency, concurrency; ~14 Gnani calls + 1-2 LLM calls
  python -m kavach.cli say "line" ...     # run caller line(s) through guard OFF and guard ON, side by side
       --lang hinglish --customer C001 --voice --condition phone_noisy
       (--voice: speak the line with Timbre, pass it through the phone line, transcribe with Prisma)

`say` is how crowd-submitted attack lines get tested: paste the comment, get both outcomes.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import sys
import time
from pathlib import Path

from .agent import Agent
from .bank import Bank
from .channel import apply_condition
from .config import CACHE_DIR, llm_settings
from .langs import LANGS
from .llm import MockLLM, OpenAICompatLLM
from .textnorm import cer, same_script, wer

SMOKE_LINES = {
    "en": "My date of birth is 12 March 1968. Please block my card ending 4 8 2 1.",
    "hi": "मेरी जन्मतिथि 12 मार्च 1968 है। मेरा बैलेंस बताइए।",
    "hinglish": "Meri DOB 12 March 1968 hai. Mera balance kitna hai?",
    "kn": "ನನ್ನ ಜನ್ಮ ದಿನಾಂಕ 12 ಮಾರ್ಚ್ 1968. ನನ್ನ ಬ್ಯಾಲೆನ್ಸ್ ಹೇಳಿ.",
}


def _llm(spec: str | None):
    return MockLLM() if spec == "mock" else OpenAICompatLLM(llm_settings(spec), use_cache=False)


def smoke(a: argparse.Namespace) -> None:
    from .speech import GnaniSpeech

    out = CACHE_DIR / "smoke"
    out.mkdir(parents=True, exist_ok=True)
    sp = GnaniSpeech(use_cache=False)
    print("== Gnani TTS -> phone line -> STT round trips")
    for lang, line in SMOKE_LINES.items():
        try:
            t = sp.tts(line, lang, voice=LANGS[lang]["caller_voices"][0])
            (out / f"{lang}_tts.wav").write_bytes(t.wav)
            for cond in ("clean", "phone_noisy"):
                wav = apply_condition(t.wav, cond, seed=1)
                (out / f"{lang}_{cond}.wav").write_bytes(wav)
                s = sp.stt(wav, lang)
                cmp_ok = same_script(line, s.text)
                w = f"WER {wer(line, s.text):.2f} CER {cer(line, s.text):.2f}" if cmp_ok else "script differs"
                print(f"[{lang:8s}] {cond:11s} TTS {t.latency_ms:6.0f} ms | STT {s.latency_ms:6.0f} ms | {w}")
                print(f"           heard: {s.text}")
        except Exception as exc:
            print(f"[{lang}] FAILED: {exc}")
    print(f"   audio saved in {out}")

    print("\n== Concurrency: two TTS requests at the same time")
    def one(i: int):
        t0 = time.perf_counter()
        try:
            sp.tts(f"Test number {i}.", "en", voice="Kaveri")
            return f"ok in {(time.perf_counter()-t0)*1000:.0f} ms"
        except Exception as exc:
            return f"error: {str(exc)[:120]}"
    with cf.ThreadPoolExecutor(2) as ex:
        for i, r in enumerate(ex.map(one, (1, 2)), 1):
            print(f"   request {i}: {r}")
    print("   (an error mentioning '1 active request' means: keep the benchmark sequential)")

    print("\n== LLM brain with tools")
    try:
        llm = _llm(a.llm)
        agent = Agent(llm, Bank(), "C001", "en", guard_enabled=True)
        r = agent.handle_turn("Hi, my date of birth is 12 March 1968. What is my balance?")
        print(f"   {llm.label}: {r.llm_calls} call(s), {r.llm_ms:.0f} ms")
        for e in r.tool_events:
            print(f"   tool {e.name}({json.dumps(e.args, ensure_ascii=False)}) -> {e.decision['action'] if e.decision else '-'}")
        print(f"   reply: {r.reply}")
        if r.error:
            print(f"   ERROR: {r.error}")
    except Exception as exc:
        print(f"   FAILED: {exc}")
    print(f"\nReal Gnani calls made: {sp.calls}. Compare your credit balance on app.gnani.ai/voice "
          "before and after to learn the cost per call.")


def say(a: argparse.Namespace) -> None:
    lines = a.lines
    heard = list(lines)
    if a.voice:
        from .speech import GnaniSpeech

        sp = GnaniSpeech()
        heard = []
        for line in lines:
            t = sp.tts(line, a.lang, voice=LANGS[a.lang]["caller_voices"][0])
            s = sp.stt(apply_condition(t.wav, a.condition, seed=1), a.lang)
            heard.append(s.text)
    llm = _llm(a.llm)
    report = {}
    for mode in ("off", "on"):
        bank = Bank()
        agent = Agent(llm, bank, a.customer, a.lang, guard_enabled=(mode == "on"))
        turns = [agent.handle_turn(h) for h in heard]
        cust = bank.customer(a.customer)
        report[mode] = {"turns": [t.as_dict() for t in turns], "transfers": cust.transfers,
                        "mobile_updates": cust.mobile_updates}
        print(f"\n===== GUARD {mode.upper()} =====")
        for t in turns:
            print(f"caller : {t.heard}")
            for e in t.tool_events:
                d = e.decision
                verdict = "EXECUTED" if e.executed else (d["action"].upper() + " " + ",".join(d["rules"]) if d else "failed")
                print(f"  tool : {e.name}({json.dumps(e.args, ensure_ascii=False)}) -> {verdict}")
            for f in t.findings:
                print(f"  flag : {f['kind']}: {f['detail']}")
            if t.error:
                print(f"  ERROR: {t.error[:200]}  (check your LLM key in .env)")
            print(f"agent  : {t.reply}")
        moved = [f"₹{x['amount_inr']:,.0f} -> {x['to_raw']}" for x in cust.transfers]
        print(f"money moved: {moved or 'none'}   mobile changed: {cust.mobile_updates or 'no'}")
    if a.json:
        Path(a.json).write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"\nsaved {a.json}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="kavach")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("smoke", help="check keys, latency and limits")
    p.add_argument("--llm", default=None)
    p.set_defaults(fn=smoke)
    p = sub.add_parser("say", help="run caller line(s) with the guard off and on")
    p.add_argument("lines", nargs="+")
    p.add_argument("--lang", default="hinglish", choices=list(LANGS))
    p.add_argument("--customer", default="C001", choices=["C001", "C002", "C003"])
    p.add_argument("--voice", action="store_true", help="speak via Timbre, phone line, Prisma")
    p.add_argument("--condition", default="phone_noisy", choices=["clean", "phone", "phone_noisy"])
    p.add_argument("--llm", default=None)
    p.add_argument("--json", default=None, help="save the full trace to this file")
    p.set_defaults(fn=say)
    a = ap.parse_args(argv)
    try:
        a.fn(a)
    except ValueError as exc:  # missing keys etc.
        sys.exit(f"error: {exc}")


if __name__ == "__main__":
    main()
