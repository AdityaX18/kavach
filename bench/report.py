"""Turn a run folder (results.jsonl, transcripts.jsonl, meta.json) into report.md + summary.json."""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from kavach.stats import bootstrap_ci, fmt_rate, mcnemar_exact, median, percentile, wilson


def _load(out: Path) -> tuple[list[dict], list[dict], dict]:
    rows = [json.loads(x) for x in (out / "results.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()] \
        if (out / "results.jsonl").exists() else []
    trs = [json.loads(x) for x in (out / "transcripts.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()] \
        if (out / "transcripts.jsonl").exists() else []
    meta = json.loads((out / "meta.json").read_text()) if (out / "meta.json").exists() else {}
    return rows, trs, meta


def _pair(rows: list[dict], a: dict, b: dict, outcome: str) -> tuple[int, int, int]:
    """Paired comparison on the same scenarios. Returns (n_pairs, b, c):
    b = outcome true under A only, c = outcome true under B only."""
    def sel(f):
        return {r["id"]: r for r in rows if all(r[k] == v for k, v in f.items())}
    A, B = sel(a), sel(b)
    ids = sorted(set(A) & set(B))
    bb = sum(1 for i in ids if A[i][outcome] and not B[i][outcome])
    cc = sum(1 for i in ids if B[i][outcome] and not A[i][outcome])
    return len(ids), bb, cc


def write_report(out: Path) -> Path:
    out = Path(out)
    rows, trs, meta = _load(out)
    errored = [r for r in rows if r.get("errors")]
    rows = [r for r in rows if not r.get("errors")]
    conds = [c for c in meta.get("conditions", []) if any(r["condition"] == c for r in rows)]
    guards = [g for g in ("off", "on") if any(r["guard"] == g for r in rows)]
    L: list[str] = []
    summary: dict = {"meta": meta, "n_rows": len(rows), "n_errored": len(errored)}
    mock = "mock" in str(meta.get("llm", "")) or meta.get("speech") == "mock"

    L.append(f"# Kavach benchmark report\n")
    if mock:
        L.append("> **MOCK RUN. These numbers come from offline stand-ins and must not be reported.**\n")
    L.append(f"- LLM brain: `{meta.get('llm')}`  ·  speech: `{meta.get('speech') or 'none (text only)'}`")
    L.append(f"- Conditions: {', '.join(conds)}  ·  guard settings: {', '.join(guards)}")
    L.append(f"- Scored calls: {len(rows)} (+{len(errored)} excluded for API errors)")
    L.append("- Rates are shown as `rate [95% Wilson CI] (k/n)`. Guard off vs on is an exact McNemar test "
             "on the same scenarios (paired).\n")

    # ------------------------------------------------------------ headline
    L.append("## 1. Attacks: how often did something unsafe actually happen?\n")
    L.append("| condition | guard OFF (policy in prompt only) | guard ON (Kavach) | paired McNemar p |")
    L.append("|---|---|---|---|")
    summary["attacks"] = {}
    for c in conds:
        cells = []
        for g in ("off", "on"):
            sub = [r for r in rows if r["kind"] == "attack" and r["condition"] == c and r["guard"] == g]
            k = sum(r["unsafe"] for r in sub)
            cells.append(fmt_rate(k, len(sub)) if sub else "-")
            summary["attacks"][f"{c}|{g}"] = {"k": k, "n": len(sub)}
        n, b, cc = _pair(rows, {"kind": "attack", "condition": c, "guard": "off"},
                         {"kind": "attack", "condition": c, "guard": "on"}, "unsafe")
        p = mcnemar_exact(b, cc) if n else float("nan")
        summary["attacks"][f"{c}|mcnemar"] = {"pairs": n, "off_only": b, "on_only": cc, "p": p}
        L.append(f"| {c} | {cells[0]} | {cells[1]} | {p:.2g} (off-only {b}, on-only {cc}, pairs {n}) |" if n
                 else f"| {c} | {cells[0]} | {cells[1]} | - |")

    L.append("\n## 2. Real customers: did their task get done?\n")
    L.append("| condition | success, guard OFF | success, guard ON | false blocks by the guard |")
    L.append("|---|---|---|---|")
    summary["benign"] = {}
    for c in conds:
        cells = []
        for g in ("off", "on"):
            sub = [r for r in rows if r["kind"] == "benign" and r["condition"] == c and r["guard"] == g]
            k = sum(bool(r["success"]) for r in sub)
            cells.append(fmt_rate(k, len(sub)) if sub else "-")
            summary["benign"][f"{c}|{g}"] = {"k": k, "n": len(sub)}
        on = [r for r in rows if r["kind"] == "benign" and r["condition"] == c and r["guard"] == "on"]
        fb = sum(r["false_block"] for r in on)
        L.append(f"| {c} | {cells[0]} | {cells[1]} | {fmt_rate(fb, len(on)) if on else '-'} |")

    # ------------------------------------------------------------ ASR effect
    audio = [c for c in conds if c != "gold"]
    if "gold" in conds and audio:
        L.append("\n## 3. What the phone line does (same scenarios, exact text vs Prisma transcript)\n")
        L.append("| comparison | guard | outcome | gold-only | audio-only | pairs | McNemar p |")
        L.append("|---|---|---|---|---|---|---|")
        for c in audio:
            for g in guards:
                for kind, outcome in (("benign", "success"), ("attack", "unsafe")):
                    n, b, cc = _pair(rows, {"kind": kind, "condition": "gold", "guard": g},
                                     {"kind": kind, "condition": c, "guard": g}, outcome)
                    if n:
                        L.append(f"| gold vs {c} | {g} | {outcome} ({kind}) | {b} | {cc} | {n} | {mcnemar_exact(b, cc):.2g} |")
        L.append("\n*Benign success lost on audio but present on gold text = failures caused by speech "
                 "recognition, not by the language model.*")

    # ------------------------------------------------------------ breakdowns
    L.append("\n## 4. By attack family (all conditions pooled)\n")
    L.append("| family | unsafe, guard OFF | unsafe, guard ON |")
    L.append("|---|---|---|")
    for fam in sorted({r["family"] for r in rows if r["kind"] == "attack"}):
        cells = []
        for g in ("off", "on"):
            sub = [r for r in rows if r["family"] == fam and r["guard"] == g]
            cells.append(fmt_rate(sum(r["unsafe"] for r in sub), len(sub)) if sub else "-")
        L.append(f"| {fam} | {cells[0]} | {cells[1]} |")

    L.append("\n## 5. By language (all conditions pooled)\n")
    L.append("| language | attacks unsafe OFF | attacks unsafe ON | benign success OFF | benign success ON |")
    L.append("|---|---|---|---|---|")
    for lang in ("en", "hi", "hinglish", "kn"):
        cells = []
        for kind, outcome in (("attack", "unsafe"), ("benign", "success")):
            for g in ("off", "on"):
                sub = [r for r in rows if r["lang"] == lang and r["kind"] == kind and r["guard"] == g]
                cells.append(fmt_rate(sum(bool(r[outcome]) for r in sub), len(sub)) if sub else "-")
        if any(cell != "-" for cell in cells):
            L.append(f"| {lang} | " + " | ".join(cells) + " |")

    L.append("\n## 6. Unsafe outcomes by type\n")
    for g in guards:
        cnt = Counter(e.split(":")[0] for r in rows if r["guard"] == g for e in r["unsafe_events"])
        L.append(f"- guard {g.upper()}: " + (", ".join(f"{k} x{v}" for k, v in cnt.most_common()) or "none"))

    # detector recall on scam-signal attacks
    sig = ("authority_safe_account", "injection_transfer", "injection_system", "coached_victim")
    on_sig = [r for r in rows if r["guard"] == "on" and r["family"] in sig]
    if on_sig:
        L.append("\n## 7. Did the guard's detectors notice the scam signals?\n")
        L.append("| condition | flagged |")
        L.append("|---|---|")
        for c in conds:
            sub = [r for r in on_sig if r["condition"] == c]
            if sub:
                L.append(f"| {c} | {fmt_rate(sum(bool(r['risk_flags']) for r in sub), len(sub))} |")
        L.append("\n*If recall drops on audio, look at the transcripts: English words spoken inside Hindi/Kannada "
                 "come back in native script, and each miss becomes a new lexicon entry.*")

    # ------------------------------------------------------------ ASR + latency
    if trs:
        L.append("\n## 8. Speech recognition (Prisma) error rates\n")
        L.append("| language | condition | WER mean [95% CI] | CER mean [95% CI] | n |")
        L.append("|---|---|---|---|---|")
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for t in trs:
            groups[(t["lang"], t["condition"])].append(t)
        mean = lambda xs: sum(xs) / len(xs)  # noqa: E731
        for (lang, c), ts in sorted(groups.items()):
            w = [t["wer"] for t in ts if t["wer"] is not None]
            ce = [t["cer"] for t in ts if t["cer"] is not None]
            if not w:
                L.append(f"| {lang} | {c} | output script differs from reference (not comparable) | | {len(ts)} |")
                continue
            we, wl, wh = bootstrap_ci(w, mean)
            cee, cl, chh = bootstrap_ci(ce, mean)
            L.append(f"| {lang} | {c} | {we:.3f} [{wl:.3f}, {wh:.3f}] | {cee:.3f} [{cl:.3f}, {chh:.3f}] | {len(w)} |")

    L.append("\n## 9. Latency (real calls only; cached calls excluded)\n")
    L.append("| stage | p50 ms | p95 ms | n |")
    L.append("|---|---|---|---|")
    stt = [t["stt_ms"] for t in trs if t.get("stt_ms")]
    tts = [t["tts_ms"] for t in trs if t.get("tts_ms")]
    llm_turns = [t["llm_ms"] for r in rows for t in r["turns"] if t["llm_calls"] and not t["llm_cached_calls"]]
    guard_turns = [t["guard_ms"] for r in rows if r["guard"] == "on" for t in r["turns"]]
    for name, xs in (("Prisma STT (REST)", stt), ("Timbre TTS (REST)", tts),
                     ("LLM per turn (all tool steps)", llm_turns), ("Kavach guard per turn", guard_turns)):
        if xs:
            L.append(f"| {name} | {median(xs):.1f} | {percentile(xs, 0.95):.1f} | {len(xs)} |")
    summary["latency_ms"] = {
        "stt_p50": median(stt) if stt else None, "llm_turn_p50": median(llm_turns) if llm_turns else None,
        "guard_turn_p50": median(guard_turns) if guard_turns else None,
    }

    # ------------------------------------------------------------ examples
    ex = [r for r in rows if r["guard"] == "off" and r["unsafe"]][:6]
    if ex:
        L.append("\n## 10. Examples: what went wrong without the guard\n")
        for r in ex:
            t = r["turns"][-1]
            L.append(f"- **{r['id']}** ({r['condition']}): heard *\"{t['heard'][:140]}\"* -> "
                     f"unsafe: {', '.join(r['unsafe_events'])}. Agent said: *\"{t['reply'][:140]}\"*")

    L.append("\n## Limitations\n")
    L.append("- Synthetic, scripted callers; callers do not adapt to the agent's replies.")
    L.append("- Test audio is Timbre TTS transcribed by Prisma (same vendor), which can flatter recognition; "
             "human recordings are reported separately when available.")
    L.append("- Phone audio is simulated (8 kHz, band-pass, mu-law, pink noise), not a real PSTN line.")
    L.append("- The leak check matches account facts written as digits; facts spoken as words are not caught.")
    L.append("- Kannada lines need native-speaker review (flagged in scenarios.jsonl).")

    path = out / "report.md"
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    return path


if __name__ == "__main__":
    print(write_report(Path(sys.argv[1])))
