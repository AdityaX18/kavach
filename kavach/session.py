"""State of one phone call. Shared by the tools (which set facts) and the guard (which reads them)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PendingTransfer:
    payee_key: str
    payee_label: str
    amount_inr: float
    turn: int  # the caller turn in which the read-back was requested


@dataclass
class Session:
    customer_id: str  # from caller ID: the telephony layer tells us whose phone is calling
    lang: str = "en"
    verified: bool = False  # set ONLY by verify_caller after a real date-of-birth check
    failed_verifications: int = 0
    locked: bool = False
    turn: int = 0
    # sticky risk signals seen during the call: kind -> phrases that matched
    flags: dict[str, list[str]] = field(default_factory=dict)
    pending_transfer: PendingTransfer | None = None
    last_caller_text: str = ""

    def add_flag(self, kind: str, phrase: str) -> None:
        self.flags.setdefault(kind, [])
        if phrase not in self.flags[kind]:
            self.flags[kind].append(phrase)
