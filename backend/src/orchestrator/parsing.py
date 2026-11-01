"""Small parsers for the deterministic planner: amounts, prepayment mode, transaction ids, yes/no."""

from __future__ import annotations

import re

WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
         "ten": 10, "fifteen": 15, "twenty": 20, "twenty-five": 25, "thirty": 30, "forty": 40, "fifty": 50,
         "sixty": 60, "seventy": 70, "seventy-five": 75, "eighty": 80, "ninety": 90, "hundred": 100}
SCALE = {"k": 1000, "thousand": 1000, "lakh": 100000, "lakhs": 100000, "l": 100000, "lac": 100000,
         "crore": 10000000}
AMOUNT = re.compile(r"(?:₹|rs\.?|inr|rupees)?\s*(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|lakhs?|lac|l|crore)?\b", re.I)
WORD_AMOUNT = re.compile(r"\b(" + "|".join(sorted(WORDS, key=len, reverse=True)) + r")\s+(thousand|lakhs?|lac|crore)\b", re.I)
TXN = re.compile(r"\bTX-\d+-\d{8}-\d\b", re.I)


def parse_amount(text: str) -> float | None:
    """Largest money-looking amount in the text, e.g. '₹50,000', '50k', 'twenty thousand', '1.5 lakh'."""
    best = None
    for m in AMOUNT.finditer(text):
        value = float(m.group(1).replace(",", ""))
        if m.group(2):
            value *= SCALE[m.group(2).lower()]
        context = text[max(0, m.start() - 12):m.end() + 8].lower()
        if not m.group(2) and value < 1000 and "₹" not in context and "rs" not in context:
            continue  # small bare numbers are counts ("6 months"), not money
        if re.search(r"\b(month|months|year|years|emis?|instalments?|days?)\b", text[m.end():m.end() + 10].lower()):
            continue
        best = value if best is None else max(best, value)
    for m in WORD_AMOUNT.finditer(text):
        value = WORDS[m.group(1).lower()] * SCALE[m.group(2).lower()]
        best = value if best is None else max(best, value)
    return best


def parse_mode(text: str) -> str | None:
    t = text.lower()
    if re.search(r"(reduce|lower|cut|smaller).{0,15}emi|emi.{0,15}(reduce|lower|smaller)", t):
        return "reduce_emi"
    if "tenure" in t or re.search(r"(shorter|fewer|finish).{0,20}(loan|emis|months)", t):
        return "reduce_tenure"
    return None


def parse_txn(text: str) -> str | None:
    m = TXN.search(text)
    return m.group(0).upper() if m else None


# Words browser speech recognition commonly mishears in servicing calls (Indian English), and their meaning.
ASR_FIXES = [
    (re.compile(r"\b(field|filed|fails|faild|fell)\s+(payments?|debits?|emis?|transactions?)", re.I), r"failed \2"),
    (re.compile(r"\b(e\s?m\s?i|emmy|emi's|amy)\b", re.I), "EMI"),
    (re.compile(r"\bpre[\s-]+pay", re.I), "prepay"),
    (re.compile(r"\b(four|for)\s*closure", re.I), "foreclosure"),
    (re.compile(r"\binstall?ments?\b", re.I), "EMIs"),
]


def normalize_speech(text: str) -> str:
    """Undo common speech-recognition slips before intent matching ("field payments" -> "failed payments")."""
    for pattern, repl in ASR_FIXES:
        text = pattern.sub(repl, text)
    return text


AFFIRM = re.compile(r"^\s*(yes|yeah|yep|sure|ok(ay)?|go ahead|confirm(ed)?|do it|please do|proceed|haan)\b", re.I)


def is_affirmative(text: str) -> bool:
    return bool(AFFIRM.search(text))
