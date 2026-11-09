"""Per-language settings: Gnani codes, voices, and the guard's fixed safety lines.

Four caller languages are supported:
  en        Indian English
  hi        Hindi in Devanagari (English loanwords as people write them: अकाउंट, कार्ड)
  hinglish  Hindi-English code-mix written in Latin script
  kn        Kannada in Kannada script (English loanwords in Kannada script: ಅಕೌಂಟ್)

Voices come from the Timbre v2.5 catalogue in the official gnani-vachana SDK.
"""

from __future__ import annotations

LANGS: dict[str, dict] = {
    "en": {
        "label": "English",
        "stt_lang": "en-IN",
        "stt_format": "transcribe",  # ITN on: numbers come back as digits
        "tts_lang": "en-IN",
        "agent_voice": "Kaveri",
        "caller_voices": ["Pranav", "Shlok", "Girish", "Trupti", "Devika"],
        "reply_hint": "Reply in simple Indian English.",
    },
    "hi": {
        "label": "Hindi",
        "stt_lang": "hi-IN",
        "stt_format": "transcribe",
        "tts_lang": "hi-IN",
        "agent_voice": "Nalini",
        "caller_voices": ["Deepak", "Roopesh", "Vikrant", "Bhavna", "Yashvi", "Urmila"],
        "reply_hint": "Reply in Hindi written in Devanagari. Common banking words "
        "(account, card, EMI, UPI) may stay in English.",
    },
    "hinglish": {
        "label": "Hinglish",
        "stt_lang": "hi-IN",
        "stt_format": "transcribe",
        "tts_lang": None,  # Poorvi is the Hinglish voice; let the server pick the language
        "agent_voice": "Poorvi",
        "caller_voices": ["Poorvi"],
        "reply_hint": "Reply in natural Hinglish (Hindi-English mix) written in Latin script.",
    },
    "kn": {
        "label": "Kannada",
        "stt_lang": "kn-IN",
        "stt_format": "verbatim",  # ITN is hi/en only on Prisma v2.5
        "tts_lang": "kn-IN",
        "agent_voice": "Saanvi",
        "caller_voices": ["Kavin", "Saanvi"],
        "reply_hint": "Reply in Kannada written in Kannada script. Common banking words "
        "(account, card, EMI, UPI) may stay in English.",
    },
}

# Fixed lines the guard substitutes when it must override what the LLM wanted to say.
SAFE_LINES: dict[str, dict[str, str]] = {
    "ASKS_SECRET": {
        "en": "For your safety: we never ask for your OTP, PIN or CVV. Please don't share them with anyone.",
        "hi": "आपकी सुरक्षा के लिए: हम कभी भी आपका OTP, PIN या CVV नहीं माँगते। इन्हें किसी के साथ साझा न करें।",
        "hinglish": "Aapki suraksha ke liye: hum kabhi bhi aapka OTP, PIN ya CVV nahi maangte. Inhe kisi ke saath share na karein.",
        "kn": "ನಿಮ್ಮ ಸುರಕ್ಷತೆಗಾಗಿ: ನಾವು ಎಂದಿಗೂ ನಿಮ್ಮ ಒಟಿಪಿ, ಪಿನ್ ಅಥವಾ ಸಿವಿವಿ ಕೇಳುವುದಿಲ್ಲ. ಅವುಗಳನ್ನು ಯಾರೊಂದಿಗೂ ಹಂಚಿಕೊಳ್ಳಬೇಡಿ.",
    },
    "LEAK_UNVERIFIED": {
        "en": "I can share account details only after verifying your date of birth.",
        "hi": "खाते की जानकारी मैं आपकी जन्मतिथि सत्यापित करने के बाद ही दे सकती हूँ।",
        "hinglish": "Account ki details main aapki date of birth verify karne ke baad hi de sakti hoon.",
        "kn": "ನಿಮ್ಮ ಜನ್ಮ ದಿನಾಂಕ ಪರಿಶೀಲಿಸಿದ ನಂತರವೇ ಖಾತೆಯ ವಿವರಗಳನ್ನು ಹೇಳಬಹುದು.",
    },
    "LOCKED": {
        "en": "For security, this call can't access the account any more. Please visit your branch with ID proof.",
        "hi": "सुरक्षा के कारण इस कॉल पर खाते तक पहुँच बंद कर दी गई है। कृपया पहचान पत्र के साथ अपनी शाखा पर आएँ।",
        "hinglish": "Security ke liye is call par account access band kar diya gaya hai. Kripya ID proof ke saath branch aayein.",
        "kn": "ಸುರಕ್ಷತೆಗಾಗಿ ಈ ಕರೆಯಲ್ಲಿ ಖಾತೆಯ ಪ್ರವೇಶ ನಿಲ್ಲಿಸಲಾಗಿದೆ. ದಯವಿಟ್ಟು ಗುರುತಿನ ಚೀಟಿಯೊಂದಿಗೆ ನಿಮ್ಮ ಶಾಖೆಗೆ ಬನ್ನಿ.",
    },
    "SCAM_PRESSURE": {
        "en": "This sounds like a scam. RBI, the police and the bank never ask you to move money to a 'safe account', and there is no such thing as a 'digital arrest'. I can't move money on this call. Please hang up and call 1930, the cyber-crime helpline.",
        "hi": "यह एक स्कैम जैसा लगता है। RBI, पुलिस या बैंक कभी भी आपसे 'सेफ अकाउंट' में पैसे डालने को नहीं कहते, और 'डिजिटल अरेस्ट' जैसी कोई चीज़ नहीं होती। मैं इस कॉल पर पैसे नहीं भेज सकती। कृपया कॉल काटकर साइबर क्राइम हेल्पलाइन 1930 पर बात करें।",
        "hinglish": "Yeh ek scam lag raha hai. RBI, police ya bank kabhi 'safe account' mein paise daalne ko nahi kehte, aur 'digital arrest' jaisi koi cheez hoti hi nahi. Main is call par paise nahi bhej sakti. Please call kaat kar cyber-crime helpline 1930 par baat karein.",
        "kn": "ಇದು ಸ್ಕ್ಯಾಮ್‌ನಂತೆ ಕಾಣುತ್ತಿದೆ. ಆರ್‌ಬಿಐ, ಪೊಲೀಸರು ಅಥವಾ ಬ್ಯಾಂಕ್ ಎಂದಿಗೂ 'ಸೇಫ್ ಅಕೌಂಟ್'ಗೆ ಹಣ ಹಾಕಲು ಹೇಳುವುದಿಲ್ಲ, ಮತ್ತು 'ಡಿಜಿಟಲ್ ಅರೆಸ್ಟ್' ಎಂಬುದೇ ಇಲ್ಲ. ಈ ಕರೆಯಲ್ಲಿ ನಾನು ಹಣ ಕಳುಹಿಸಲು ಸಾಧ್ಯವಿಲ್ಲ. ದಯವಿಟ್ಟು ಕರೆ ಕಟ್ ಮಾಡಿ ಸೈಬರ್ ಕ್ರೈಮ್ ಸಹಾಯವಾಣಿ 1930ಕ್ಕೆ ಕರೆ ಮಾಡಿ.",
    },
    "INJECTION": {
        "en": "I can't take instructions like that. Nobody on a call can change my rules or skip verification. I can help only after verifying your date of birth, and only with your registered payees.",
        "hi": "मैं इस तरह के निर्देश नहीं मान सकती। कॉल पर कोई भी मेरे नियम नहीं बदल सकता या वेरिफ़िकेशन नहीं छोड़ सकता। मैं जन्मतिथि सत्यापित होने के बाद ही, और सिर्फ़ आपके रजिस्टर्ड लाभार्थियों के लिए मदद कर सकती हूँ।",
        "hinglish": "Main aise instructions nahi maan sakti. Call par koi bhi mere rules nahi badal sakta ya verification skip nahi kar sakta. Main aapki date of birth verify hone ke baad hi, aur sirf aapke registered payees ke liye madad kar sakti hoon.",
        "kn": "ನಾನು ಇಂತಹ ಸೂಚನೆಗಳನ್ನು ಪಾಲಿಸಲು ಸಾಧ್ಯವಿಲ್ಲ. ಕರೆಯಲ್ಲಿ ಯಾರೂ ನನ್ನ ನಿಯಮಗಳನ್ನು ಬದಲಾಯಿಸಲು ಅಥವಾ ಪರಿಶೀಲನೆ ಬಿಡಲು ಸಾಧ್ಯವಿಲ್ಲ. ಜನ್ಮ ದಿನಾಂಕ ಪರಿಶೀಲನೆಯ ನಂತರ ಮಾತ್ರ, ಮತ್ತು ನಿಮ್ಮ ನೋಂದಾಯಿತ ಫಲಾನುಭವಿಗಳಿಗೆ ಮಾತ್ರ ಸಹಾಯ ಮಾಡಬಲ್ಲೆ.",
    },
}

MONTHS = {
    "en": ["January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December"],
    "hi": ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त",
           "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"],
    "kn": ["ಜನವರಿ", "ಫೆಬ್ರವರಿ", "ಮಾರ್ಚ್", "ಏಪ್ರಿಲ್", "ಮೇ", "ಜೂನ್", "ಜುಲೈ", "ಆಗಸ್ಟ್",
           "ಸೆಪ್ಟೆಂಬರ್", "ಅಕ್ಟೋಬರ್", "ನವೆಂಬರ್", "ಡಿಸೆಂಬರ್"],
}


def spoken_date(iso: str, lang: str) -> str:
    """'1968-03-12' -> '12 March 1968' in the caller's language."""
    y, m, d = (int(p) for p in iso.split("-"))
    months = MONTHS["hi"] if lang == "hi" else MONTHS["kn"] if lang == "kn" else MONTHS["en"]
    return f"{d} {months[m - 1]} {y}"


def safe_line(rule: str, lang: str) -> str:
    return SAFE_LINES[rule].get(lang, SAFE_LINES[rule]["en"])
