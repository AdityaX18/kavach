"""Run the Kavach benchmark.

Examples
  # offline plumbing check (no keys, MOCK numbers, never report them)
  python -m bench.run --llm mock --speech mock --conditions gold,phone_noisy --langs en,hinglish

  # cheapest real run: text only (no Gnani credits), both guard settings
  python -m bench.run --llm groq --conditions gold

  # the headline run: gold text vs 8 kHz phone + noise, through Prisma
  python -m bench.run --llm groq --conditions gold,phone_noisy --yes

Phases
  1. audio: every unique caller line -> Timbre TTS (caller voice) -> phone channel -> Prisma STT
  2. calls: every scenario x condition x guard(off/on) -> agent -> independent grader
  3. report: rates with Wilson 95% CIs, exact McNemar for guard off vs on, WER/CER, latency
Everything is cached and resumable: re-running the same command continues where it stopped.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

from bench.evaluate import evaluate
from bench.recordings import load_human
from bench.report import write_report
from bench.scenarios import build
from kavach.agent import Agent
from kavach.bank import Bank
from kavach.channel import CONDITIONS, apply_condition
from kavach.config import ROOT, llm_settings
from kavach.langs import LANGS
from kavach.llm import MockLLM, OpenAICompatLLM
from kavach.speech import GnaniSpeech, MockSpeech
from kavach.textnorm import cer, same_script, wer


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def pick_voice(text: str, lang: str) -> str:
    voices = LANGS[lang]["caller_voices"]
    return voices[int(_sha(text), 16) % len(voices)]


def _filter(scns: list[dict], field: str, value: str) -> list[dict]:
    if value == "all":
        return scns
    keep = set(value.split(","))
    return [s for s in scns if s[field] in keep]


def stratified(scns: list[dict], limit: int) -> list[dict]:
    """Take `limit` scenarios round-robin across (kind, family, lang) so small runs stay balanced."""
    if not limit or limit >= len(scns):
        return scns
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for s in scns:
        groups[(s["kind"], s["family"], s["lang"])].append(s)
    out: list[dict] = []
    keys = sorted(groups)
    i = 0
    while len(out) < limit:
        progressed = False
        for k in keys:
            if i < len(groups[k]) and len(out) < limit:
                out.append(groups[k][i])
                progressed = True
        if not progressed:
            break
        i += 1
    return out


def make_llm(spec: str | None, use_cache: bool = True):
    if spec == "mock":
        return MockLLM()
    return OpenAICompatLLM(llm_settings(spec), use_cache=use_cache)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--llm", default=None, help="groq | groq:<model> | gemini | ollama | openai_compat | mock")
    ap.add_argument("--speech", default="gnani", choices=["gnani", "mock"])
    ap.add_argument("--conditions", default="gold,phone_noisy",
                    help="comma list from: gold," + ",".join(CONDITIONS) + ",human,human_noisy")
    ap.add_argument("--human-dir", default=None, help="folder of your recordings named <ID>.wav/.m4a "
                    "(and <ID>__noisy.*), IDs from docs/RECORDING_SHEET.md")
    ap.add_argument("--guard", default="both", choices=["both", "on", "off"])
    ap.add_argument("--langs", default="all", help="e.g. hi,hinglish,kn,en")
    ap.add_argument("--kinds", default="all", help="benign,attack")
    ap.add_argument("--families", default="all")
    ap.add_argument("--customers", default="all")
    ap.add_argument("--limit", type=int, default=0, help="max scenarios, balanced across families/languages")
    ap.add_argument("--out", default=None, help="output folder (default runs/<llm>-<time>)")
    ap.add_argument("--repeats", type=int, default=1,
                    help="run every scenario N times with the LLM cache off: measures how OFTEN an attack "
                         "works, since the same call can go differently each time")
    ap.add_argument("--yes", action="store_true", help="don't ask before spending API calls")
    ap.add_argument("--today", default="2026-11-07", help="fixed date in the prompt, keeps runs comparable")
    a = ap.parse_args(argv)

    conditions = [c.strip() for c in a.conditions.split(",") if c.strip()]
    human_conds = [c for c in conditions if c in ("human", "human_noisy")]
    for c in conditions:
        if c not in ("gold", "human", "human_noisy") and c not in CONDITIONS:
            sys.exit(f"unknown condition {c}")
    if human_conds and not a.human_dir:
        sys.exit("--human-dir is required for human / human_noisy conditions")
    audio_conds = [c for c in conditions if c in CONDITIONS]
    guards = {"both": [False, True], "on": [True], "off": [False]}[a.guard]

    scns = build()
    for field, val in (("lang", a.langs), ("kind", a.kinds), ("family", a.families), ("customer_id", a.customers)):
        scns = _filter(scns, field, val)
    scns = stratified(scns, a.limit)
    if not scns:
        sys.exit("no scenarios match the filters")

    repeats = max(1, a.repeats)
    llm = make_llm(a.llm, use_cache=repeats == 1)
    speech = None
    if audio_conds or human_conds:
        speech = MockSpeech() if a.speech == "mock" else GnaniSpeech()

    out = Path(a.out) if a.out else ROOT / "runs" / f"{llm.label.replace(':', '_').replace('/', '_')}-{time.strftime('%Y%m%d-%H%M')}"
    out.mkdir(parents=True, exist_ok=True)
    meta = {"llm": llm.label, "speech": speech.label if speech else None, "conditions": conditions,
            "guards": ["on" if g else "off" for g in guards], "n_scenarios": len(scns), "repeats": repeats,
            "started": time.strftime("%Y-%m-%d %H:%M:%S"), "argv": sys.argv[1:]}
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    print(f"[kavach] {len(scns)} scenarios x {len(conditions)} conditions x {len(guards)} guard settings"
          f"{f' x {repeats} repeats' if repeats > 1 else ''} -> {out}")

    # ---------------------------------------------------------------- phase 1: audio
    transcripts: dict[tuple[str, str, str], str] = {}
    if audio_conds:
        needed = sorted({(t, s["lang"]) for s in scns for t in s["turns"]})
        n_tts, n_stt = len(needed), len(needed) * len(audio_conds)
        print(f"[audio] {n_tts} unique caller lines -> up to {n_tts} TTS + {n_stt} STT calls "
              "(cached ones are free).")
        if a.speech == "gnani" and not a.yes and n_tts + n_stt > 40:
            if input("Spend these Gnani credits? [y/N] ").strip().lower() != "y":
                sys.exit("aborted")
        tpath = out / "transcripts.jsonl"
        with tpath.open("w", encoding="utf-8") as tf:
            for i, (text, lang) in enumerate(needed, 1):
                voice = pick_voice(text, lang)
                try:
                    tts = speech.tts(text, lang, voice=voice)
                except Exception as exc:
                    print(f"  TTS failed for {lang}: {text[:40]!r}: {exc}")
                    continue
                for cond in audio_conds:
                    wav = apply_condition(tts.wav, cond, seed=int(_sha(text)[:8], 16))
                    try:
                        st = speech.stt(wav, lang, ref_text=text, condition=cond)
                    except Exception as exc:
                        print(f"  STT failed ({cond}) for {lang}: {text[:40]!r}: {exc}")
                        continue
                    transcripts[(text, lang, cond)] = st.text
                    comparable = same_script(text, st.text)
                    tf.write(json.dumps({
                        "lang": lang, "condition": cond, "voice": voice, "ref": text, "hyp": st.text,
                        "wer": wer(text, st.text) if comparable else None,
                        "cer": cer(text, st.text) if comparable else None,
                        "script_match": comparable,
                        "stt_ms": None if st.cached else round(st.latency_ms, 1),
                        "tts_ms": None if tts.cached else round(tts.latency_ms, 1),
                        "server": st.meta,
                    }, ensure_ascii=False) + "\n")
                if i % 10 == 0 or i == len(needed):
                    print(f"  audio {i}/{len(needed)}  real calls so far: {speech.calls}")

    if human_conds:
        files = load_human(Path(a.human_dir))
        print(f"[human] {len(files)} recordings found in {a.human_dir}")
        with (out / "transcripts.jsonl").open("a", encoding="utf-8") as tf:
            for (text, lang, cond), path in sorted(files.items()):
                if cond not in human_conds:
                    continue
                try:
                    st = speech.stt(path.read_bytes(), lang, filename=path.name, ref_text=text, condition=cond)
                except Exception as exc:
                    print(f"  STT failed for {path.name}: {exc}")
                    continue
                transcripts[(text, lang, cond)] = st.text
                comparable = same_script(text, st.text)
                tf.write(json.dumps({
                    "lang": lang, "condition": cond, "voice": "human", "ref": text, "hyp": st.text,
                    "wer": wer(text, st.text) if comparable else None,
                    "cer": cer(text, st.text) if comparable else None, "script_match": comparable,
                    "stt_ms": None if st.cached else round(st.latency_ms, 1), "tts_ms": None,
                    "server": st.meta, "file": path.name,
                }, ensure_ascii=False) + "\n")

    # ---------------------------------------------------------------- phase 2: calls
    rpath = out / "results.jsonl"
    done = set()
    if rpath.exists():
        for line in rpath.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(line)["key"])
            except Exception:
                pass
    total = len(scns) * len(conditions) * len(guards) * repeats
    n = len(done)
    t_start = time.time()
    with rpath.open("a", encoding="utf-8") as rf:
        for s in scns:
            for cond in conditions:
                if cond != "gold" and any((t, s["lang"], cond) not in transcripts for t in s["turns"]):
                    continue  # audio failed for this scenario: skip rather than guess
                for rep in range(repeats):
                    for g in guards:
                        rid = s["id"] if repeats == 1 else f"{s['id']}#r{rep}"
                        key = f"{rid}|{cond}|{'on' if g else 'off'}"
                        if key in done:
                            continue
                        bank = Bank()
                        agent = Agent(llm, bank, s["customer_id"], s["lang"], guard_enabled=g, today=a.today)
                        turns = []
                        for t in s["turns"]:
                            heard = t if cond == "gold" else transcripts[(t, s["lang"], cond)]
                            turns.append(agent.handle_turn(heard))
                        ev = evaluate(s, bank, turns)
                        row = {"key": key, "id": rid, "scenario_id": s["id"], "repeat": rep, "kind": s["kind"],
                               "family": s["family"], "lang": s["lang"], "customer_id": s["customer_id"],
                               "condition": cond, "guard": "on" if g else "off", "llm": llm.label, **ev,
                               "turns": [t.as_dict() for t in turns]}
                        rf.write(json.dumps(row, ensure_ascii=False) + "\n")
                        rf.flush()
                        n += 1
                        if n % 10 == 0 or n == total:
                            el = time.time() - t_start
                            print(f"  calls {n}/{total}  ({el/60:.1f} min)")

    # ---------------------------------------------------------------- phase 3: report
    report = write_report(out)
    print(f"[report] {report}")


if __name__ == "__main__":
    main()
