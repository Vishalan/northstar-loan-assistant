"""Grounding check: every number in a reply must come from a tool output or the customer.

Numbers are extracted from the reply (₹ amounts with Indian grouping, percentages, plain numbers) and
matched against every number found in this turn's tool outputs, earlier turns' facts and the customer's
own words. Small counts (<= 10) are not checked; years must appear in a tool output too. A rounded figure ("about ₹23,000") passes
when it is within 3% of a known figure.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation

# digits inside identifiers ("PL-20391", "SR-261101-DA197A", "TX-18822-…") are names, not figures
NUMBER = re.compile(r"(?<![\w.])(?<![A-Za-z]-)(?<!\d-)(₹\s?)?(\d[\d,]*(?:\.\d+)?)(?![\w-]*[A-Za-z])(\s?%)?")
WORD_NUMBERS = {"thousand": 1000, "lakh": 100000, "lakhs": 100000, "crore": 10000000}


def _to_decimal(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None


def numbers_in(text: str) -> list[tuple[str, Decimal]]:
    found = []
    for m in NUMBER.finditer(text):
        value = _to_decimal(m.group(2))
        if value is None:
            continue
        tail = text[m.end():m.end() + 8].lower()
        for word, mult in WORD_NUMBERS.items():
            if re.match(rf"\s*{word}\b", tail):
                value *= mult
                break
        found.append((m.group(0).strip(), value))
    return found


def collect_allowed(*objects) -> set[Decimal]:
    allowed: set[Decimal] = set()

    def walk(obj):
        if isinstance(obj, bool) or obj is None:
            return
        if isinstance(obj, (int, float, Decimal)):
            d = Decimal(str(obj))
            allowed.add(d)
            allowed.add(d.quantize(Decimal(1)))
            allowed.add(abs(d))
        elif isinstance(obj, str):
            for _, v in numbers_in(obj):
                allowed.add(v)
                allowed.add(v.quantize(Decimal(1)))
        elif isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, (list, tuple, set)):
            for v in obj:
                walk(v)

    for o in objects:
        walk(json.loads(json.dumps(o, default=str)) if not isinstance(o, str) else o)
    return allowed


def unsupported(text: str, allowed: set[Decimal]) -> list[str]:
    bad = []
    for raw, value in numbers_in(text):
        if value <= 10:  # small counts ("two options"); years are checked like any other number
            continue
        if value in allowed or value.quantize(Decimal("0.01")) in allowed:
            continue
        if value >= 1000 and value % 100 == 0 and any(a > 0 and abs(value - a) / a <= Decimal("0.03") for a in allowed):
            continue
        bad.append(raw)
    return bad


SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z₹\"'(])|\n{2,}")


def split_sentences(buffer: str) -> tuple[list[str], str]:
    """Complete sentences from a streaming buffer, plus the unfinished remainder."""
    parts = SENTENCE_END.split(buffer)
    if len(parts) == 1:
        return [], buffer
    return [p for p in parts[:-1] if p.strip()], parts[-1]
