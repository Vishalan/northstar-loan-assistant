"""Money helpers: Decimal arithmetic and Indian-style formatting (₹8,00,000)."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal("0")
PAISA = Decimal("0.01")
RUPEE = Decimal("1")


def D(value) -> Decimal:
    """Coerce numbers and numeric strings to Decimal without float artefacts."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def to_rupee(value) -> Decimal:
    return D(value).quantize(RUPEE, rounding=ROUND_HALF_UP)


def to_paisa(value) -> Decimal:
    return D(value).quantize(PAISA, rounding=ROUND_HALF_UP)


def group_indian(integer_digits: str) -> str:
    """'800000' -> '8,00,000' (last three digits, then pairs)."""
    if len(integer_digits) <= 3:
        return integer_digits
    head, tail = integer_digits[:-3], integer_digits[-3:]
    pairs = []
    while len(head) > 2:
        pairs.insert(0, head[-2:])
        head = head[:-2]
    if head:
        pairs.insert(0, head)
    return ",".join(pairs + [tail])


def inr(value, paise: bool = False) -> str:
    """Format as ₹ with Indian grouping. Whole rupees unless paise=True."""
    amount = to_paisa(value) if paise else to_rupee(value)
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    text = f"{amount:.2f}" if paise else f"{amount:.0f}"
    if "." in text:
        whole, frac = text.split(".")
        return f"{sign}₹{group_indian(whole)}.{frac}"
    return f"{sign}₹{group_indian(text)}"


def pct(value, places: int = 2) -> str:
    q = Decimal(1).scaleb(-places)
    return f"{D(value).quantize(q, rounding=ROUND_HALF_UP)}%"


MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def fmt_date(d: date | str) -> str:
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    days_in_month = [31, 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28,
                     31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return date(year, month, min(d.day, days_in_month))


def months_between(start: date, end: date) -> int:
    """Whole months elapsed from start to end."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return months
