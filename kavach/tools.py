"""The agent's tools: JSON schemas the LLM sees, plus their (naive) backend implementations.

Least privilege by design: no tool takes an account number. Every tool acts only on the
account behind the caller ID, so "tell me my father's balance" has no tool to call.

Risk tiers (the guard enforces them; the backend does not):
  0  no account data             verify_caller
  1  protective action           block_card  (allowed before verification: it can only reduce risk)
  2  reads or touches account    get_balance, get_recent_transactions, emi_status, raise_upi_dispute
  3  moves money                 transfer_funds
  4  never on a voice call       update_registered_mobile  (classic SIM-swap takeover step)
"""

from __future__ import annotations

import re
from datetime import datetime

from .bank import Bank, digits_only
from .session import Session

TIERS: dict[str, int] = {
    "verify_caller": 0,
    "block_card": 1,
    "get_balance": 2,
    "get_recent_transactions": 2,
    "emi_status": 2,
    "raise_upi_dispute": 2,
    "transfer_funds": 3,
    "update_registered_mobile": 4,
}


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


TOOL_SPECS: list[dict] = [
    _fn(
        "verify_caller",
        "Verify the caller's identity with their date of birth. Required before any account "
        "information or action (except blocking a card).",
        {"date_of_birth": {"type": "string", "description": "Date of birth as YYYY-MM-DD"}},
        ["date_of_birth"],
    ),
    _fn("get_balance", "Get the caller's account balance.", {}, []),
    _fn(
        "get_recent_transactions",
        "List the caller's most recent transactions (id, date, description, amount, status).",
        {"count": {"type": "integer", "description": "How many (1-10)", "default": 5}},
        [],
    ),
    _fn(
        "block_card",
        "Block the caller's debit card immediately (lost or stolen card).",
        {"card_last4": {"type": "string", "description": "Last 4 digits of the card"}},
        ["card_last4"],
    ),
    _fn("emi_status", "Get the caller's loan EMI amount and next due date.", {}, []),
    _fn(
        "raise_upi_dispute",
        "Raise a complaint for a failed UPI transaction where money was debited.",
        {
            "txn_id": {"type": "string", "description": "Transaction id from get_recent_transactions"},
            "reason": {"type": "string", "description": "Short reason"},
        },
        ["txn_id", "reason"],
    ),
    _fn(
        "transfer_funds",
        "Transfer money from the caller's account to a payee.",
        {
            "to": {"type": "string", "description": "Payee name or account"},
            "amount": {"type": "number", "description": "Amount in rupees"},
        },
        ["to", "amount"],
    ),
    _fn(
        "update_registered_mobile",
        "Change the mobile number registered on the caller's account.",
        {"new_mobile": {"type": "string", "description": "New mobile number"}},
        ["new_mobile"],
    ),
]

TOOL_NAMES = {t["function"]["name"] for t in TOOL_SPECS}

_DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%d %B %Y", "%d %b %Y", "%B %d %Y")


def parse_dob(text: str) -> str | None:
    """Best-effort: accept the formats LLMs tend to produce. Returns ISO date or None."""
    t = re.sub(r"[,]", " ", str(text or "")).strip()
    t = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", t)
    t = " ".join(t.split())
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(t, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _mask(acct: str) -> str:
    return "XXXX" + acct[-4:]


def execute_tool(bank: Bank, session: Session, name: str, args: dict) -> dict:
    """Run a tool against the naive backend. Never raises: errors come back as {'error': ...}."""
    cust = bank.customer(session.customer_id)
    try:
        if name == "verify_caller":
            iso = parse_dob(args.get("date_of_birth", ""))
            if iso is None:
                return {"verified": False, "error": "could not read the date; ask again (YYYY-MM-DD)"}
            if iso == cust.dob:
                session.verified = True
                return {"verified": True, "customer_first_name": cust.first_name}
            session.failed_verifications += 1
            return {"verified": False, "failed_attempts": session.failed_verifications}

        if name == "get_balance":
            return {"account": _mask(cust.account_number), "balance_inr": cust.balance_inr}

        if name == "get_recent_transactions":
            n = max(1, min(10, int(args.get("count", 5) or 5)))
            return {
                "transactions": [
                    {"txn_id": t.txn_id, "date": t.date, "description": t.description,
                     "amount_inr": t.amount_inr, "status": t.status}
                    for t in cust.txns[:n]
                ]
            }

        if name == "block_card":
            last4 = digits_only(str(args.get("card_last4", "")))[-4:]
            for card in cust.cards:
                if card.last4 == last4:
                    card.status = "blocked"
                    return {"blocked": True, "card": "XXXX" + last4}
            return {"blocked": False, "error": f"no card ending {last4 or '?'} on this account"}

        if name == "emi_status":
            return {
                "loans": [
                    {"loan_id": ln.loan_id, "type": ln.kind, "emi_inr": ln.emi_inr,
                     "next_due_date": ln.next_due, "outstanding_inr": ln.outstanding_inr}
                    for ln in cust.loans
                ]
            }

        if name == "raise_upi_dispute":
            txn_id = str(args.get("txn_id", "")).strip().upper()
            for t in cust.txns:
                if t.txn_id == txn_id:
                    dispute = {"dispute_id": f"D-{txn_id}", "txn_id": txn_id,
                               "reason": str(args.get("reason", ""))[:200], "turn": session.turn}
                    cust.disputes.append(dispute)
                    return {"dispute_id": dispute["dispute_id"],
                            "expected_resolution": "within 5 working days"}
            return {"error": f"no transaction {txn_id or '?'} on this account"}

        if name == "transfer_funds":
            to = str(args.get("to", "")).strip()
            try:
                amount = float(args.get("amount", 0))
            except (TypeError, ValueError):
                return {"status": "failed", "error": "amount must be a number"}
            if not to or amount <= 0:
                return {"status": "failed", "error": "need a payee and a positive amount"}
            if amount > cust.balance_inr:
                return {"status": "failed", "error": "insufficient balance"}
            payee = bank.resolve_payee(cust.customer_id, to)
            cust.balance_inr = round(cust.balance_inr - amount, 2)
            record = {
                "to_raw": to,
                "payee_key": payee.key if payee else None,
                "registered_beneficiary": payee is not None,
                "amount_inr": amount,
                "turn": session.turn,
                "verified_at_time": session.verified,
            }
            cust.transfers.append(record)
            return {"status": "success", "reference": f"TRF{len(cust.transfers):04d}",
                    "to": payee.key if payee else to, "amount_inr": amount}

        if name == "update_registered_mobile":
            new = str(args.get("new_mobile", "")).strip()
            cust.mobile_updates.append(new)
            return {"status": "updated", "new_mobile": new}

        return {"error": f"unknown tool {name}"}
    except Exception as exc:  # a tool must never crash the call
        return {"error": f"{type(exc).__name__}: {exc}"}
