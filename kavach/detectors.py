"""Multilingual phrase detectors used by the guard.

Why lexicons and not another LLM: they are fast (microseconds), deterministic, explainable
in an interview, and they cannot be prompt-injected. Their weakness is recall: a new
phrasing slips past. That is exactly what the public red-team is for: every phrase the
crowd finds that slips past becomes a new entry here, and the benchmark shows the effect.

Important detail for Indian speech: when someone says English words inside Hindi or
Kannada, ASR writes them in the native script. "Ignore your instructions" spoken in a
Hindi sentence comes back as "इग्नोर योर इंस्ट्रक्शंस". So each list carries Latin,
Devanagari and Kannada spellings of the same idea, including transliterated English.
"""

from __future__ import annotations

import re
import unicodedata

# ZWNJ, ZWJ, Devanagari nukta are dropped; chandrabindu -> anusvara (हाँ == हां).
_TRANSLATE = {0x200C: None, 0x200D: None, 0x093C: None, 0x0901: 0x0902}


def norm(text: str) -> str:
    """Lowercase, NFC, drop invisible joiners/nukta, punctuation -> space, collapse spaces."""
    t = unicodedata.normalize("NFC", text or "").translate(_TRANSLATE).lower()
    out = []
    for ch in t:
        cat = unicodedata.category(ch)
        out.append(" " if cat.startswith("P") or cat.startswith("S") else ch)
    return " ".join("".join(out).split())


LEXICON: dict[str, list[str]] = {
    # someone claiming to be police / RBI / a government or bank authority
    "authority_claim": [
        "rbi officer", "rbi se", "rbi ki taraf", "from rbi", "reserve bank of india", "rbi notice",
        "cbi", "cyber cell", "cyber crime", "cybercrime", "cyber unit", "crime branch",
        "enforcement directorate", "ed office", "narcotics", "nia", "national investigation agency",
        "trai", "inspector", "digital arrest", "arrest", "arrested", "giraftar", "giraftaar", "giraftari",
        "warrant", "money laundering", "hawala", "terror funding", "drugs", "fir",
        "courier parcel", "parcel seized", "raid", "fake passports", "head office audit", "supreme court notice",
        "सीबीआई", "साइबर क्राइम", "साइबर सेल", "क्राइम ब्रांच", "इंस्पेक्टर", "गिरफ्तार", "अरेस्ट",
        "वारंट", "मनी लॉन्ड्रिंग", "प्रवर्तन निदेशालय", "ट्राई", "ड्रग्स", "एफआईआर", "नारकोटिक्स",
        "रिजर्व बैंक", "आरबीआई",
        "ಆರ್ಬಿಐ", "ಆರ್ ಬಿ ಐ", "ರಿಸರ್ವ್ ಬ್ಯಾಂಕ್", "ಸಿಬಿಐ", "ಸೈಬರ್", "ಕ್ರೈಂ", "ಇನ್ಸ್ಪೆಕ್ಟರ್", "ಬಂಧನ",
        "ಅರೆಸ್ಟ್", "ವಾರಂಟ್", "ಮನಿ ಲಾಂಡರಿಂಗ್", "ಡ್ರಗ್ಸ್", "ಎಫ್ಐಆರ್",
    ],
    # everyday words that are also scam words: logged, and blocking only with a claim + a money demand
    "authority_mention": [
        "rbi", "reserve bank", "police", "court", "judge", "magistrate", "income tax", "customs",
        "investigation", "jaanch", "thana", "thane se", "sarkari", "government officer",
        "पुलिस", "अदालत", "कोर्ट", "जांच", "थाने", "थाना", "कस्टम", "इनकम टैक्स", "सरकारी अधिकारी",
        "ಪೊಲೀಸ್", "ಪೋಲೀಸ್", "ನ್ಯಾಯಾಲಯ", "ಕೋರ್ಟ್", "ತನಿಖೆ", "ಕಸ್ಟಮ್ಸ್", "ಸರ್ಕಾರಿ ಅಧಿಕಾರಿ",
    ],
    # someone claiming to be bank staff (a customer never needs to say this)
    "staff_claim": [
        "branch manager", "bank manager", "it team", "audit team", "head office", "supervisor",
        "fraud department", "fraud team", "security team", "employee id", "bank official",
        "मैनेजर", "हेड ऑफिस", "ಮ್ಯಾನೇಜರ್", "ಹೆಡ್ ಆಫೀಸ್",
    ],
    # attempts to rewrite the agent's rules ("prompt injection", spoken)
    "injection": [
        "ignore all", "ignore your", "ignore previous", "ignore the rules", "ignore every",
        "forget your", "forget all", "previous instructions", "new instructions",
        "system prompt", "system update", "system message", "developer mode", "admin mode",
        "admin override", "override code", "override your", "jailbreak", "you are now", "act as if",
        "act as a bank", "pretend you", "pretend to be", "pretend that", "disregard", "testing mode",
        "test mode", "debug mode", "maintenance mode", "safety checks are off", "checks are off",
        "sudo", "no verify", "whitelisted", "follow my commands", "my commands", "your only job",
        "without verification", "without checks", "verification not required", "no verification",
        "verification step already", "repeat after me", "translation task",
        "forget everything", "no restrictions", "no rules", "with no rules", "do anything now",
        "hypothetically", "imagine you", "training exercise", "demonstrate a transfer", "simulate",
        "assume i did", "end of customer message", "bank instructions", "respond only with",
        "tool call", "transfer funds", "write a story", "real values", "caller verified", "verified true", "ignor all",
        "instrukshun", "instrukshuns", "verifyed", "naya order", "zarurat nahi", "zaroorat nahi",
        "bina verification", "bina rules", "rules lagu nahi", "admin mode", "tumhara developer",
        "maine tumhe banaya", "jo main bolu", "maan lo", "game khelte", "test mode", "dost ki tarah",
        "आदेश मानोगे", "नियम नहीं", "मान लो", "टेस्ट मोड", "ज़रूरत नहीं", "जरूरत नहीं",
        "ಯಾವುದೇ ನಿಯಮಗಳಿಲ್ಲ", "ಊಹಿಸಿ", "ಟೆಸ್ಟ್ ಮೋಡ್", "ನಾನು ಹೇಳಿದಂತೆ",
        "already verified", "caller is verified", "verification is disabled",
        "verification disabled", "skip verification", "bypass", "no need to verify",
        "verification band", "verification skip", "verify mat karo", "niyam bhool",
        "rules bhool", "instructions bhool", "pichle instructions", "pichle saare",
        "इग्नोर", "निर्देश भूल", "नियम भूल", "पिछले निर्देश", "पिछले सारे निर्देश",
        "सिस्टम प्रॉम्प्ट", "सिस्टम अपडेट", "डेवलपर मोड", "एडमिन", "ओवरराइड",
        "पहले से वेरिफाइड", "पहले से सत्यापित", "वेरिफिकेशन बंद", "वेरिफिकेशन छोड़",
        "सत्यापन की जरूरत नहीं", "इंस्ट्रक्शन", "इंस्ट्रक्शंस", "डेवलपर", "ऑलरेडी वेरिफ", "वेरिफिएड है",
        "ಇಗ್ನೋರ್", "ಸೂಚನೆಗಳನ್ನು ಮರೆ", "ನಿಯಮಗಳನ್ನು ಮರೆ", "ಹಿಂದಿನ ಎಲ್ಲಾ ಸೂಚನೆ",
        "ಹಿಂದಿನ ಸೂಚನೆ", "ಡೆವಲಪರ್ ಮೋಡ್", "ಸಿಸ್ಟಮ್ ಅಪ್ಡೇಟ್", "ಸಿಸ್ಟಮ್ ಪ್ರಾಂಪ್ಟ್",
        "ಈಗಾಗಲೇ ವೆರಿಫೈ", "ವೆರಿಫಿಕೇಶನ್ ಆಫ್", "ವೆರಿಫಿಕೇಶನ್ ಬೇಡ", "ಪರಿಶೀಲನೆ ಬೇಡ",
        "ಇನ್ಸ್ಟ್ರಕ್ಷನ್",
    ],
    # signs that a (possibly genuine) customer is being coached by a scammer
    "coercion": [
        "safe account", "secure account", "safety account", "rbi account",
        "told me to transfer", "told me to move", "asked me to transfer", "asked me to move",
        "on the other line", "other line", "stay on the call", "officer said", "officer told",
        "officer ne kaha", "officer ne bola", "doosri line", "dusri line", "surakshit khate",
        "secure holding account", "holding account", "protected account", "escrow", "safe locker",
        "verification account", "investigation account", "court account", "not to tell anyone",
        "don t tell anyone", "kisi ko mat batana", "do not disconnect", "don t disconnect",
        "not to disconnect", "call mat kaatna", "keep the camera on", "video call", "account they gave",
        "unke diye account", "surakshit khate", "paise surakshit",
        "सेफ अकाउंट", "सुरक्षित खाते", "सुरक्षित खाता", "दूसरी लाइन", "अधिकारी ने कहा", "अधिकारी हैं",
        "खतरे में", "फ़ोन मत काटिए", "फोन मत काटिए", "किसी को मत बताना",
        "ಸೇಫ್ ಅಕೌಂಟ್", "ಸುರಕ್ಷಿತ ಖಾತೆ", "ಇನ್ನೊಂದು ಲೈನ್", "ಕರೆ ಕಟ್ ಮಾಡಬೇಡಿ", "ಅಧಿಕಾರಿ ಹೇಳಿದ್ದಾರೆ",
        "ಅಧಿಕಾರಿ ಇದ್ದಾರೆ",
    ],
    # pressure words: logged, not blocking on their own (real emergencies exist)
    "urgency": [
        "urgent", "urgently", "immediately", "right now", "emergency", "turant", "jaldi",
        "abhi ke abhi", "तुरंत", "जल्दी", "अभी के अभी", "इमरजेंसी",
        "ತಕ್ಷಣ", "ಈಗಲೇ", "ಬೇಗ", "ತುರ್ತು", "ಎಮರ್ಜೆನ್ಸಿ",
    ],
    # asking about someone else's account: logged (tools can't reach other accounts anyway)
    "third_party": [
        "my father", "my mother", "my husband", "my wife", "his account", "her account",
        "on behalf", "papa ke", "pitaji", "mummy ke", "maa ke", "पापा", "पिताजी", "माँ के",
        "उनका बैलेंस", "उनके खाते", "ನಮ್ಮ ತಂದೆ", "ಅಪ್ಪನ", "ಅಮ್ಮನ", "ಅವರ ಬ್ಯಾಲೆನ್ಸ್", "ಅವರ ಖಾತೆ",
    ],
    # secrets a bank must never ask for or hear
    "secret_mention": [
        "otp", "one time password", "pin", "mpin", "upi pin", "atm pin", "cvv", "password",
        "ओटीपी", "पिन", "सीवीवी", "पासवर्ड", "ಒಟಿಪಿ", "ಓಟಿಪಿ", "ಪಿನ್", "ಸಿವಿವಿ", "ಪಾಸ್ವರ್ಡ್",
    ],
}

# Context, used by assess(): is the caller DEMANDING money/data, CLAIMING an identity, or ASKING about a scam?
MONEY_DEMAND = [
    "transfer", "send", "pay", "move", "deposit", "wire", "shift", "jama", "bhejo", "bhej do",
    "bhejiye", "daalo", "daal do", "dalo", "fee", "fees", "penalty", "fine", "clearance",
    "भेज", "डाल", "जमा", "ट्रांसफर", "भरिए", "भरो", "जुर्माना", "फीस",
    "ಕಳುಹಿಸ", "ಹಾಕಿ", "ಹಾಕಲು", "ವರ್ಗಾಯಿಸ", "ಕಟ್ಟಿ", "ಟ್ರಾನ್ಸ್ಫರ್", "ದಂಡ",
]
CLAIM_CTX = [
    "this is", "i am", "i m", "calling from", "call from", "here", "speaking", "department",
    "bol raha", "bol rahe", "se call", "se hoon", "se bol", "ki taraf se", "main",
    "बोल रहा", "बोल रहे", "से कॉल", "से बोल", "की तरफ से", "मैं", "ನಾನು", "ಇಂದ ಕರೆ", "ಇಂದ ಮಾತನಾಡ",
    "ಇಲಾಖೆಯಿಂದ", "ದಿಂದ ಕರೆ",
]
QUESTION_CTX = [
    "is that real", "is it real", "is this real", "should i report", "what should i do",
    "someone called", "someone asked", "i got a message", "i got a call", "claiming to be",
    "kya ye sach", "sach hai", "kya karu", "call aaya", "complaint kar di", "police complaint",
    "police station", "filed a", "retired", "works in", "can i talk",
    "सच है", "किसी ने फोन", "शिकायत कर दी", "क्या करूँ", "क्या करें", "how do we report", "report it", "fraud hai na", "ಮೋಸವೇ", "ನಿಜವೇ", "ಕರೆ ಮಾಡಿದರು", "ದೂರು ಕೊಟ್ಟಿದ್ದೇನೆ",
]

AFFIRM = [
    "yes", "yeah", "yep", "yup", "sure", "correct", "confirm", "confirmed", "ok", "okay",
    "go ahead", "proceed", "do it", "please do", "haan", "haanji", "haa", "han ji", "ji haan",
    "theek hai", "thik hai", "kar do", "kardo", "bhej do", "bhejo", "kar dijiye",
    "bhej dijiye", "हां", "जी हां", "ठीक है", "कर दो", "कर दीजिए", "भेज दो", "भेज दीजिए",
    "भेजिए", "कन्फर्म", "ಹೌದು", "ಸರಿ", "ಮಾಡಿ", "ಕಳುಹಿಸಿ", "ಓಕೆ", "ಕನ್ಫರ್ಮ್",
]
NEGATE = [
    "no", "nope", "not", "don t", "dont", "cancel", "stop", "never mind", "wrong", "nahi",
    "nahin", "mat", "ruko", "galat", "नहीं", "मत", "रुको", "रुकिए", "कैंसल", "गलत",
    "ಇಲ್ಲ", "ಬೇಡ", "ನಿಲ್ಲಿಸಿ", "ಕ್ಯಾನ್ಸಲ್", "ತಪ್ಪು",
]

# For spotting the agent *asking* for a secret (vs warning about one).
REQUEST_WORDS = [
    "tell", "share", "give", "say", "read", "provide", "send", "enter", "speak", "confirm",
    "bataiye", "batayein", "batao", "bata dijiye", "dijiye", "boliye", "share kijiye",
    "बताइए", "बताएं", "बताओ", "बता दीजिए", "दीजिए", "बोलिए", "शेयर",
    "ಹೇಳಿ", "ಕೊಡಿ", "ತಿಳಿಸಿ", "ಹಂಚಿಕೊಳ್ಳಿ", "ಹೇಳು",
]
WARNING_WORDS = [
    "never", "do not", "don t", "dont", "not share", "kabhi", "mat", "na karein", "nahi",
    "कभी", "मत", "न करें", "नहीं", "ಎಂದಿಗೂ", "ಬೇಡ", "ಹಂಚಿಕೊಳ್ಳಬೇಡಿ",
]


def _compile(terms: list[str]) -> tuple[re.Pattern | None, list[str]]:
    """Latin terms -> one regex with word boundaries. Indic terms -> substring list.

    (Python's \\b is unreliable inside Indic words because vowel signs are not 'word'
    characters, so Indic terms use plain substring matching after normalisation.)
    """
    latin = sorted({norm(t) for t in terms if norm(t).isascii()}, key=len, reverse=True)
    indic = sorted({norm(t) for t in terms if not norm(t).isascii()}, key=len, reverse=True)
    pat = None
    if latin:
        pat = re.compile(r"(?<![a-z0-9])(?:" + "|".join(map(re.escape, latin)) + r")(?![a-z0-9])")
    return pat, indic


_COMPILED = {k: _compile(v) for k, v in LEXICON.items()}
_AFFIRM = _compile(AFFIRM)
_NEGATE = _compile(NEGATE)
_REQUEST = _compile(REQUEST_WORDS)
_WARNING = _compile(WARNING_WORDS)
_SECRET = _COMPILED["secret_mention"]


def _find(compiled: tuple[re.Pattern | None, list[str]], normed: str) -> list[str]:
    pat, indic = compiled
    hits: list[str] = []
    if pat is not None:
        hits += [m.group(0) for m in pat.finditer(normed)]
    hits += [t for t in indic if t in normed]
    return list(dict.fromkeys(hits))


def detect(text: str) -> dict[str, list[str]]:
    """Return {kind: [matched phrases]} for every lexicon kind that fires."""
    n = norm(text)
    found = {}
    for kind, comp in _COMPILED.items():
        hits = _find(comp, n)
        if hits:
            found[kind] = hits
    return found


_MONEY = _compile(MONEY_DEMAND)
_CLAIM = _compile(CLAIM_CTX)
_QUESTION = _compile(QUESTION_CTX)
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})


def deobfuscate(text: str) -> str:
    """'1gn0re' -> 'ignore', 'i g n o r e' -> 'ignore'. Only touches tokens that mix letters and digits."""
    toks = []
    for tok in (text or "").split():
        if re.search(r"[a-zA-Z]", tok) and re.search(r"[0-9@$]", tok):
            tok = tok.translate(_LEET)
        toks.append(tok)
    s = " ".join(toks)
    return re.sub(r"\b(?:[a-zA-Z] ){3,}[a-zA-Z]\b", lambda m: m.group(0).replace(" ", ""), s)


def assess(text: str) -> dict[str, list[str]]:
    """detect() plus context. The rules, in plain words:
      - injection always counts.
      - strong authority claims (CBI, digital arrest, ...) and coercion count, unless the caller
        is asking or reporting ("is that real?", "I filed a police complaint") and gives no account number.
      - everyday authority words (police, court, income tax, jaanch) count only with a claim
        ("this is ...", "main ... bol raha hoon") AND a money demand.
      - staff claims count with a claim or a money demand.
    Anything that does not count is still logged under its own name, so nothing is hidden."""
    found = detect(text)
    deob = deobfuscate(text)
    if deob != text:
        for kind, hits in detect(deob).items():
            found.setdefault(kind, [])
            found[kind] = list(dict.fromkeys(found[kind] + hits))
    n = norm(text)
    money = bool(_find(_MONEY, n))
    claim = bool(_find(_CLAIM, n))
    question = bool(_find(_QUESTION, n))
    long_number = bool(re.search(r"\d(?:[ ,-]?\d){7,}", text or ""))
    out: dict[str, list[str]] = {}
    for kind, hits in found.items():
        if kind in ("authority_claim", "coercion") and question and not long_number:
            out.setdefault("scam_question", []).extend(hits)
        elif kind == "authority_mention":
            if claim and money and not question:
                out.setdefault("authority_claim", []).extend(hits)
            else:
                out.setdefault("authority_mention", []).extend(hits)
        elif kind == "staff_claim" and not (claim or money):
            out.setdefault("staff_mention", []).extend(hits)
        else:
            out.setdefault(kind, []).extend(hits)
    return {k: list(dict.fromkeys(v)) for k, v in out.items()}


def is_affirmative(text: str) -> bool:
    n = norm(text)
    return bool(_find(_AFFIRM, n)) and not _find(_NEGATE, n)


_SENT_SPLIT = re.compile(r"(?<=[.!?।])\s+|\n+")


def asks_for_secret(reply: str) -> bool:
    """True if a sentence asks for OTP/PIN/CVV/password (and isn't a 'never share' warning)."""
    for sent in _SENT_SPLIT.split(reply or ""):
        n = norm(sent)
        if _find(_SECRET, n) and _find(_REQUEST, n) and not _find(_WARNING, n):
            return True
    return False


_SECRET_WORDS_RAW = (
    r"otp|one\s*time\s*password|m?pin|cvv|password|ओटीपी|पिन|सीवीवी|पासवर्ड|ಒಟಿಪಿ|ಓಟಿಪಿ|ಪಿನ್|ಸಿವಿವಿ"
)
_SECRET_VALUE = re.compile(
    rf"(?i)(?<![a-z])((?:{_SECRET_WORDS_RAW})\D{{0,15}}?)(\d(?:[\s-]?\d){{3,7}})(?!\d)"
)


def redact_secrets(text: str) -> tuple[str, int]:
    """'my OTP is 4 8 2 9 1 3' -> 'my OTP is [REDACTED]'. The LLM never sees the digits."""
    count = 0

    def _sub(m: re.Match) -> str:
        nonlocal count
        count += 1
        return m.group(1) + "[REDACTED]"

    return _SECRET_VALUE.sub(_sub, text or ""), count


_LONG_NUMBER = re.compile(r"\d(?:[\s-]?\d){8,}")


def mask_long_numbers(text: str) -> tuple[str, int]:
    """Any run of 9+ digits (account/card/phone numbers) -> 'XXXX' + last 4."""
    count = 0

    def _sub(m: re.Match) -> str:
        nonlocal count
        count += 1
        digits = "".join(str(unicodedata.digit(c)) for c in m.group(0) if c.isdigit())
        return "XXXX" + digits[-4:]

    return _LONG_NUMBER.sub(_sub, text or ""), count


def ascii_digits(text: str) -> str:
    return "".join(str(unicodedata.digit(c)) if c.isdigit() else c for c in text or "")


def contains_number(text: str, number: str) -> bool:
    """Does `text` say this exact number (as digits)? Separators like 48,250 are ignored."""
    t = ascii_digits(text)
    t = re.sub(r"(?<=\d)[,\s](?=\d)", "", t)
    return re.search(rf"(?<!\d){re.escape(number)}(?!\d)", t) is not None
