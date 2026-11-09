"""Kavach: a deterministic safety layer for Indian-language voice agents.

Pipeline:  caller audio -> Gnani Prisma (STT) -> Guard (caller text) -> LLM agent
           -> Guard (every tool call) -> tools on a fictional bank -> Guard (reply)
           -> Gnani Timbre (TTS) -> caller

The LLM proposes. The guard decides. The guard is plain Python: no prompt can talk it
out of its rules, because it never reads instructions, only facts (who is verified,
which payees are registered, what was confirmed, what the caller said).
"""

__version__ = "0.1.0"
