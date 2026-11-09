"""Human recordings: the script you read aloud, and how the benchmark finds your files.

  python -m bench.recordings        -> writes docs/RECORDING_SHEET.md and bench/recordings.csv

Each line has an ID (HG-01 Hinglish, HI-01 Hindi, EN-01 English, KN-01 Kannada).
Save each recording as <ID>.wav (or .m4a/.mp3) in one folder. Lines marked [noisy] are
recorded a second time somewhere loud and saved as <ID>__noisy.wav.
Then: python -m bench.run --conditions gold,human,human_noisy --human-dir <folder>

These recordings are TEST data, never training data: nothing in Kavach learns from them,
which is exactly why they are a fair test of how it handles real Indian voices.
"""

from __future__ import annotations

import csv
from pathlib import Path

from bench.scenarios import build

ROOT = Path(__file__).resolve().parent.parent
PREFIX = {"hinglish": "HG", "hi": "HI", "en": "EN", "kn": "KN"}
FAMILY_ORDER = ["hero_digital_arrest", "authority_safe_account", "coached_victim", "injection_transfer",
                "injection_system", "third_party", "pii_unverified", "mobile_change", "mobile_change_verified",
                "over_limit", "dob_bruteforce", "block_card", "balance", "transfer", "upi_dispute", "emi"]
NOISY_FAMILIES = {"hero_digital_arrest", "authority_safe_account", "coached_victim", "injection_transfer",
                  "block_card", "transfer"}


def sheet() -> list[dict]:
    """One recording per unique line. Customer-specific lines use customer C001 (Ramesh)."""
    rows, seen = [], set()
    scns = [s for s in build() if s["customer_id"] == "C001"]
    for lang in ("hinglish", "hi", "en", "kn"):
        n = 0
        for fam in FAMILY_ORDER:
            for s in scns:
                if s["lang"] != lang or s["family"] != fam:
                    continue
                for t in s["turns"]:
                    if (t, lang) in seen:
                        continue
                    seen.add((t, lang))
                    n += 1
                    rows.append({"id": f"{PREFIX[lang]}-{n:02d}", "lang": lang, "family": fam,
                                 "noisy": fam in NOISY_FAMILIES and lang in ("hinglish", "hi"), "text": t})
    return rows


def load_human(folder: Path) -> dict[tuple[str, str, str], Path]:
    """Map (text, lang, condition) -> recording file."""
    by_id = {r["id"]: r for r in sheet()}
    out = {}
    for p in folder.iterdir():
        if p.suffix.lower() not in {".wav", ".m4a", ".mp3", ".ogg", ".flac", ".aac"}:
            continue
        stem, noisy = (p.stem[:-7], True) if p.stem.endswith("__noisy") else (p.stem, False)
        r = by_id.get(stem.upper())
        if r:
            out[(r["text"], r["lang"], "human_noisy" if noisy else "human")] = p
    return out


def main() -> None:
    rows = sheet()
    with (ROOT / "bench" / "recordings.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "lang", "family", "noisy", "text"])
        w.writeheader()
        w.writerows(rows)
    names = {"hinglish": "Hinglish (you)", "hi": "Hindi (you)", "en": "English (you)",
             "kn": "Kannada (a Kannada-speaking friend, with their written OK)"}
    L = ["# Recording sheet", "",
         "Read each line naturally, the way a caller would say it on the phone. Mistakes, pauses and your",
         "own accent are GOOD: that is real Indian audio. If a line feels unnatural, say it your way and",
         "note the change next to the ID, so the reference text can be updated.",
         "",
         "- Save as `<ID>.wav` (or the phone's .m4a) into one folder, one file per line.",
         "- Quiet room first. Lines marked **[noisy]**: record again near traffic, a fan, a TV or a market",
         "  and save as `<ID>__noisy.wav`.",
         "- Phone held normally, about 15 cm from your mouth. Don't re-record to make it perfect.",
         "- Never say real numbers, Aadhaar, PAN or anyone's real details. Everything below is synthetic.",
         "- Lines with the same caller in sequence (turn 1, turn 2) are separate files.", ""]
    for lang in ("hinglish", "hi", "en", "kn"):
        sub = [r for r in rows if r["lang"] == lang]
        L += [f"## {names[lang]}: {len(sub)} lines ({sum(r['noisy'] for r in sub)} also noisy)", ""]
        for r in sub:
            tag = " **[noisy]**" if r["noisy"] else ""
            L.append(f"**{r['id']}**{tag} · *{r['family']}*  ")
            L.append(f"{r['text']}")
            L.append("")
    (ROOT / "docs" / "RECORDING_SHEET.md").write_text("\n".join(L), encoding="utf-8")
    print(f"{len(rows)} lines; noisy re-records: {sum(r['noisy'] for r in rows)}")
    for lang in PREFIX:
        print(f"  {lang}: {sum(r['lang'] == lang for r in rows)}")


if __name__ == "__main__":
    main()
