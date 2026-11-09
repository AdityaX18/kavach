"""LLM brains behind the agent.

OpenAICompatLLM talks to any OpenAI-compatible chat API with tool calling: Groq, Google
Gemini (OpenAI endpoint), Ollama, or vLLM (which can serve Gnani's open-weight Evon).
It adds what a benchmark needs: a disk cache (re-runs cost nothing, interrupted runs
resume), a client-side rate limit, and retries with backoff on 429/5xx.

MockLLM is a deterministic, deliberately *naive* agent (it does whatever the caller asks).
It exists only so the plumbing can be tested offline. Results produced with it are
labelled MOCK everywhere and must never be reported as real.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .config import CACHE_DIR, LLMSettings
from .detectors import is_affirmative, norm
from .langs import MONTHS


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict
    raw_args: str = ""
    parse_error: bool = False


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    latency_ms: float = 0.0
    cached: bool = False


def _parse_args(raw: str | None) -> tuple[dict, bool]:
    if not raw:
        return {}, False
    try:
        val = json.loads(raw)
        return (val if isinstance(val, dict) else {}), not isinstance(val, dict)
    except json.JSONDecodeError:
        return {}, True


class OpenAICompatLLM:
    def __init__(self, settings: LLMSettings, use_cache: bool = True, cache_dir: Path | None = None):
        from openai import OpenAI  # imported lazily so offline tests don't need network config

        self.settings = settings
        self.label = settings.label
        self.client = OpenAI(base_url=settings.base_url, api_key=settings.api_key or "none",
                             timeout=60.0, max_retries=0)
        self.use_cache = use_cache
        self.cache_dir = (cache_dir or CACHE_DIR) / "llm"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._last_call = 0.0

    def _key(self, messages: list[dict], tools: list[dict]) -> str:
        blob = json.dumps(
            {"m": self.settings.model, "t": self.settings.temperature, "msgs": messages, "tools": tools},
            sort_keys=True, ensure_ascii=False,
        )
        return hashlib.sha256(blob.encode()).hexdigest()

    def _throttle(self) -> None:
        gap = 60.0 / max(1, self.settings.max_rpm)
        with self._lock:
            wait = self._last_call + gap - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        key = self._key(messages, tools)
        path = self.cache_dir / f"{key}.json"
        if self.use_cache and path.exists():
            d = json.loads(path.read_text())
            return LLMResponse(
                content=d["content"],
                tool_calls=[ToolCall(**tc) for tc in d["tool_calls"]],
                latency_ms=d["latency_ms"],
                cached=True,
            )

        import openai

        delay = 2.0
        last_exc: Exception | None = None
        for _attempt in range(7):
            self._throttle()
            t0 = time.perf_counter()
            try:
                resp = self.client.chat.completions.create(
                    model=self.settings.model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    temperature=self.settings.temperature,
                    max_tokens=1024,  # gpt-oss reasons before answering
                )
                latency = (time.perf_counter() - t0) * 1000
                msg = resp.choices[0].message
                calls = []
                for tc in msg.tool_calls or []:
                    args, err = _parse_args(tc.function.arguments)
                    calls.append(ToolCall(tc.id, tc.function.name, args, tc.function.arguments or "", err))
                out = LLMResponse(msg.content, calls, latency, False)
                if self.use_cache:
                    path.write_text(json.dumps({
                        "content": out.content,
                        "tool_calls": [tc.__dict__ for tc in out.tool_calls],
                        "latency_ms": out.latency_ms,
                    }, ensure_ascii=False))
                return out
            except (openai.RateLimitError, openai.InternalServerError, openai.APIConnectionError,
                    openai.APITimeoutError) as exc:
                last_exc = exc
                retry_after = None
                try:
                    retry_after = float(exc.response.headers.get("retry-after"))  # type: ignore[union-attr]
                except Exception:
                    pass
                time.sleep(min(60.0, retry_after or delay))
                delay *= 2
        raise RuntimeError(f"LLM call failed after retries: {last_exc}")


# ---------------------------------------------------------------------------- mock
_MONTH_INDEX: dict[str, int] = {}
for _lang_months in MONTHS.values():
    for _i, _m in enumerate(_lang_months):
        _MONTH_INDEX[norm(_m)] = _i + 1

_RUPEE = r"(?:rupees|rupee|rupaye|rupay|rs|रुपये|रुपए|ರೂಪಾಯಿ)"


def _has(n: str, words: list[str]) -> bool:
    return any(norm(w) in n for w in words)


class MockLLM:
    """Naive offline stand-in. Calls whatever tool the words suggest, ignores policy."""

    label = "mock:naive"

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        if messages[-1]["role"] == "tool":
            return self._after_tools(messages)
        user = next(m["content"] for m in reversed(messages) if m["role"] == "user")
        calls = self._plan(user, messages)
        if calls:
            return LLMResponse(None, calls, 1.0)
        return LLMResponse("How can I help you with your account today?", [], 1.0)

    # -- planning from the caller's words
    def _plan(self, text: str, messages: list[dict]) -> list[ToolCall]:
        n = norm(text)  # for keywords
        low = unicodedata.normalize("NFC", text).lower()  # for numbers (keeps 9,500 intact)
        calls: list[ToolCall] = []

        def add(name: str, **args) -> None:
            calls.append(ToolCall(f"call_{len(calls)}_{name}", name, args, json.dumps(args)))

        m = re.search(r"(\d{1,2})\s+(\S+)\s+(\d{4})", n)
        if m and m.group(2) in _MONTH_INDEX:
            add("verify_caller", date_of_birth=f"{m.group(3)}-{_MONTH_INDEX[m.group(2)]:02d}-{int(m.group(1)):02d}")

        if is_affirmative(text):
            last = self._last_transfer_args(messages)
            if last:
                add("transfer_funds", **last)
                return calls

        if _has(n, ["block", "ब्लॉक", "ಬ್ಲಾಕ್"]) and _has(n, ["card", "कार्ड", "ಕಾರ್ಡ್"]):
            dm = re.search(r"(\d(?:\s?\d){3})(?!\s?\d)", n)
            add("block_card", card_last4=(dm.group(1).replace(" ", "") if dm else ""))
        if _has(n, ["balance", "बैलेंस", "ಬ್ಯಾಲೆನ್ಸ್"]):
            add("get_balance")
        if _has(n, ["emi", "ईएमआई", "ಇಎಂಐ"]):
            add("emi_status")
        if _has(n, ["complaint", "dispute", "शिकायत", "ದೂರು"]):
            add("get_recent_transactions", count=5)
        if _has(n, ["mobile", "मोबाइल", "ಮೊಬೈಲ್"]) and _has(n, ["change", "update", "badal", "बदल", "ಬದಲಾ"]):
            dm = re.search(r"(\d(?:\s?\d){6,})", n)
            add("update_registered_mobile", new_mobile=(dm.group(1) if dm else ""))
        if _has(n, ["transfer", "send", "bhej", "भेज", "ಕಳುಹಿಸ", "ಟ್ರಾನ್ಸ್ಫರ್", "ट्रांसफर", "daalo", "डालो", "ಹಾಕಿ"]):
            am = re.search(rf"(\d[\d,]*)\s*{_RUPEE}", low)
            acct = re.search(r"(?:account|अकाउंट|ಅಕೌಂಟ್)\s+((?:\d+\s?){3,})", n)
            name = (re.search(r"\bto\s+([a-z]+)", n) or re.search(r"(\S+)\s+(?:ko|को|ಅವರಿಗೆ)(?=\s|$)", n))
            to = acct.group(1).strip() if acct else (name.group(1) if name else "")
            if am:
                add("transfer_funds", to=to, amount=float(am.group(1).replace(",", "")))
        return calls

    @staticmethod
    def _last_transfer_args(messages: list[dict]) -> dict | None:
        for m in reversed(messages):
            for tc in m.get("tool_calls") or []:
                if tc["function"]["name"] == "transfer_funds":
                    return json.loads(tc["function"]["arguments"])
        return None

    # -- replying after tool results
    def _after_tools(self, messages: list[dict]) -> LLMResponse:
        results = []
        for m in reversed(messages):
            if m["role"] != "tool":
                break
            results.append(json.loads(m["content"]))
        results.reverse()
        did_dispute = any("dispute_id" in r for r in results)
        for r in results:
            if "transactions" in r and not did_dispute:
                failed = [t for t in r["transactions"] if t["status"] == "failed_debited"]
                if failed:
                    args = {"txn_id": failed[0]["txn_id"], "reason": "payment failed but money debited"}
                    return LLMResponse(None, [ToolCall("call_dispute", "raise_upi_dispute", args, json.dumps(args))], 1.0)
        parts = []
        for r in results:
            if r.get("status") == "blocked":
                parts.append("Sorry, I can't do that on this call.")
            elif r.get("status") == "confirmation_required":
                parts.append("Please confirm the transfer. Say yes or no.")
            elif r.get("status") == "success":
                parts.append(f"Transfer of {r['amount_inr']:.0f} rupees done.")
            elif "balance_inr" in r:
                parts.append(f"Your balance is {r['balance_inr']} rupees.")
            elif r.get("blocked") is True:
                parts.append("Your card is blocked.")
            elif "loans" in r:
                ln = r["loans"][0]
                parts.append(f"Your EMI of {ln['emi_inr']} rupees is due on {ln['next_due_date']}.")
            elif "dispute_id" in r:
                parts.append(f"Complaint {r['dispute_id']} raised.")
            elif r.get("verified") is True:
                parts.append("Thank you, you are verified.")
            elif r.get("status") == "updated":
                parts.append("Your mobile number is updated.")
        return LLMResponse(" ".join(parts) or "Okay.", [], 1.0)
