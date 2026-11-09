# Runbook: Sat 7 Nov → submit Tue 10 Nov (noon, hard deadline 11:59 PM IST)

## 0. Keys (5 min)
- Gnani: app.gnani.ai/voice → API key. **Write down your credit balance now.**
- Groq: console.groq.com → API Keys → create (free).
- Optional: Gemini at aistudio.google.com → Get API key (free). Better Kannada, slower.

## 1. Set up (10 min)
```bash
cd kavach
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                  # paste the keys in
python -m pytest -q                                   # expect: 22 passed
python -m kavach.cli smoke
```
`smoke` prints: TTS and STT latency per language, what Prisma heard on a clean vs phone line,
whether two requests at once are allowed, and one LLM tool call. Check credits again: (before − after) ÷ calls = cost per call.

## 2. Find REAL breaks before recording (15 min, no Gnani credits)
The demo must show what really happens. First find which attacks actually beat the unguarded agent:
```bash
python -m bench.run --llm groq:openai/gpt-oss-20b --conditions gold --kinds attack --out runs/breaks-20b
python -m bench.run --llm groq:openai/gpt-oss-120b --conditions gold --kinds attack --out runs/breaks-120b
```
Open `runs/*/report.md`. Section 10 lists real calls where money moved or data leaked without the guard.
Pick the most dramatic one that worked **in Hinglish or Kannada** for the video.
If the bigger model resists everything, say so honestly in the post. Never show a break that didn't happen.

## 3. Record the 45-second demo (30 min)
```bash
python -m app.demo --llm groq:openai/gpt-oss-120b
```
Open http://127.0.0.1:7860. Mode: Side by side. Phone line: on. Language: Hinglish (or Kannada).
Screen-record (Windows: Win+G; Mac: Cmd+Shift+5; or OBS):
1. (0-5 s) Title card: "Can you scam an AI bank agent?"
2. (5-25 s) Speak the scam line into the mic. Show "Prisma heard", then the left lane moving money, then the right lane BLOCKED with its rules.
3. (25-40 s) One benign call, e.g. block a lost card in Kannada, to show the guard doesn't break normal use.
4. (40-45 s) "Comment your best scam line. I'll run it on camera."
Add captions; most people watch muted.

## 4. Post (see POSTS.md), then nominate those posts in the submission form
Post the same day you record. Reply to every comment within a few hours.

## 5. Comment loop (Sat-Mon, 1-2 h/day)
For each scam line in the comments:
```bash
python -m kavach.cli say "<their line>" --lang hinglish --voice --json runs/crowd/<name>.json
```
or paste it into the demo's text box. Reply with a screenshot of both lanes and credit them.
**If a line beats the guard:** that's the best content you'll get. Add the phrase to `kavach/detectors.py`,
re-run, and post "v2: here is what @name found and how I fixed it."

## 6. Headline benchmark (Sun, ~1-2 h mostly waiting)
```bash
python -m bench.run --llm groq:openai/gpt-oss-20b --conditions gold,phone_noisy --yes --out runs/main
```
Uses about 188 TTS + 188 STT Gnani calls (check smoke's cost per call first; use `--limit 100` if credits are tight).
Copy the headline table from `runs/main/report.md` into README "Results".

## 7. Submit (Mon night / Tue morning)
- Public GitHub repo with README + results
- Demo video (the 45-60 s cut)
- Written explanation: problem, how the guard works, results with CIs, limitations, who built what
- Models used: Gnani Prisma v2.5 (STT), Timbre v2.5 (TTS)
- Links to the nominated LinkedIn and X posts
