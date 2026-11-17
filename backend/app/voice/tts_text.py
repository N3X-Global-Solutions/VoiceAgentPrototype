"""Spoken-form cleanup for the agent's replies, applied just before they reach the TTS.

The system prompt asks the LLM to write numbers as words. This catches the digits it
still writes, so the voice says "fourteen thousand rupees" instead of reading "14000".
Only the voice sees the rewrite: transcripts keep the text as the LLM wrote it.

It only touches sentences written mostly in Latin script (English, or Hinglish in
Latin letters). num2words has no Hindi, Tamil, Marathi, Gujarati, Punjabi or Malayalam,
so for replies in Indian scripts the prompt rule does the work, and any digit left over
goes to Sarvam's own text normalisation unchanged.
"""

import re

from num2words import num2words

_DIGITS = "zero one two three four five six seven eight nine".split()
_NUM = r"\d+(?:,\d+)*(?:\.\d+)?"
# A number standing on its own: not part of a word, a time (10:30), a date (10/11) or a version (v1.2).
_ALONE_BEFORE = r"(?<![\w:/.,])"
_ALONE_AFTER = r"(?![\w:/]|[.,]\d)"

# ₹14,000 / Rs. 500 / INR 99.50 / Rs 500/-
_RUPEES_BEFORE = re.compile(rf"(?:₹|\bRs\.?|\bINR)\s?({_NUM})(?:\s?/-)?", re.IGNORECASE)
# 14000 rupees / 500 Rs
_RUPEES_AFTER = re.compile(rf"{_ALONE_BEFORE}({_NUM})\s?(?:rupees?|rs\b\.?|inr\b)", re.IGNORECASE)
# 25 lakh / 2.5 crore
_LAKH_CRORE = re.compile(rf"{_ALONE_BEFORE}({_NUM})\s?(lakhs?|crores?)\b", re.IGNORECASE)
# OTP 4821 / PIN: 1234 / account number 00123456 / order id 77812
_CODE = re.compile(
    r"\b(otp|pin|code|account(?:\s+(?:number|no\.?))?|a/c|order(?:\s+(?:id|number|no\.?))?|"
    r"ref(?:erence)?(?:\s+(?:id|number|no\.?))?|ticket(?:\s+(?:id|number|no\.?))?|policy(?:\s+(?:number|no\.?))?)"
    r"(\s*(?:is|:|-|#)?\s*)(\d{3,})\b",
    re.IGNORECASE,
)
# +91 98765 43210 / 98765-43210 / 9876543210 (any run of 7+ digits is a code, not an amount)
_PHONE = re.compile(r"(?:\+\d{1,3}[\s-]?)?\b\d{5}[\s-]\d{5}\b|\+\d{1,3}[\s-]?\d{7,}\b|\b\d{7,}\b")
_PERCENT = re.compile(rf"{_ALONE_BEFORE}({_NUM})\s?%")
_ORDINAL = re.compile(r"\b(\d+)(st|nd|rd|th)\b", re.IGNORECASE)
_NUMBER = re.compile(rf"{_ALONE_BEFORE}({_NUM}){_ALONE_AFTER}")
_LATIN = re.compile(r"[A-Za-z]")
_LETTER = re.compile(r"[^\W\d_]")


def _words(value: str, **kwargs) -> str:
    """Indian-English words for a number: 150000 -> 'one lakh fifty thousand'."""
    number = float(value) if "." in value else int(value)
    text = num2words(number, lang="en_IN", **kwargs)
    return text.replace(",", "").replace("-", " ")


def _digit_by_digit(digits: str) -> str:
    """'9876543210' -> 'nine eight seven six five, four three two one zero'."""
    groups = [g for g in re.split(r"[\s-]+", digits.strip()) if g]
    if len(groups) == 1:
        run = groups[0]
        size = 5 if len(run) == 10 else 4
        groups = [run[i : i + size] for i in range(0, len(run), size)] if len(run) > 6 else [run]
    return ", ".join(" ".join(_DIGITS[int(d)] for d in g) for g in groups)


def _rupees(amount: str) -> str:
    amount = amount.replace(",", "")
    rupees, _, paise = amount.partition(".")
    spoken = f"{_words(rupees)} rupees"
    paise = (paise + "0")[:2] if paise else ""
    if paise and int(paise):
        spoken += f" and {_words(str(int(paise)))} paise"
    return spoken


def _mostly_latin(text: str) -> bool:
    letters = _LETTER.findall(text)
    return bool(letters) and len(_LATIN.findall(text)) * 2 >= len(letters)


def speak_numbers(text: str) -> str:
    """Rewrite the digits in an English sentence the way a person would say them."""
    if not any(c.isdigit() for c in text) or not _mostly_latin(text):
        return text
    # Money first, so a long amount like "2500000 rupees" isn't read out as a phone number.
    text = _RUPEES_BEFORE.sub(lambda m: _rupees(m[1]), text)
    text = _RUPEES_AFTER.sub(lambda m: _rupees(m[1]), text)
    text = _LAKH_CRORE.sub(lambda m: f"{_words(m[1].replace(',', ''))} {m[2].lower()}", text)
    text = _CODE.sub(lambda m: f"{m[1]}{m[2]}{_digit_by_digit(m[3])}", text)
    text = _PHONE.sub(lambda m: _digit_by_digit(m[0].lstrip("+")), text)
    text = _PERCENT.sub(lambda m: f"{_words(m[1].replace(',', ''))} percent", text)
    text = _ORDINAL.sub(lambda m: _words(m[1], to="ordinal"), text)
    return _NUMBER.sub(lambda m: _words(m[1].replace(",", "")), text)


async def tts_text_transform(text: str, _text_type) -> str:
    """Pipecat text transform: runs on each sentence just before it is sent to Sarvam TTS."""
    return speak_numbers(text)
