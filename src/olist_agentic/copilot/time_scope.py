"""Deterministic extraction of explicit calendar periods from analytics questions.

Never infer relative dates or fiscal years: Olist is a fixed historical snapshot.
Ambiguous multi-period comparisons require structured date filters instead of
silently running an all-time aggregate.
"""
from __future__ import annotations

import calendar
import re
from datetime import date

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_WORD = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?"
)
_NATURAL_DAY = re.compile(
    rf"\b({_MONTH_WORD})\s+([0-3]?\d),?\s+((?:19|20)\d{{2}})\b", re.I
)
_NATURAL_MONTH = re.compile(
    rf"\b({_MONTH_WORD})\s*,?\s*((?:19|20)\d{{2}})\b", re.I
)
_ISO_DAY = re.compile(r"(?<!\d)((?:19|20)\d{2})-(\d{2})-(\d{2})(?!\d)")
_ISO_MONTH = re.compile(r"(?<!\d)((?:19|20)\d{2})-(\d{2})(?!-\d|\d)")
_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_UNSUPPORTED_RELATIVE = re.compile(
    r"\b(?:today|yesterday|tomorrow|last month|this month|last year|"
    r"this year|next year|last week|this week|last quarter|this quarter|"
    r"fiscal year|fiscal|FY\s*20\d{2})\b", re.I
)


def explicit_calendar_period(question: str) -> tuple[str, str] | None:
    """Return inclusive purchase-date bounds for a single stated period.

    Raises for relative/fiscal or multi-period expressions rather than
    accidentally attributing an all-time number to a requested period.
    """
    if _UNSUPPORTED_RELATIVE.search(question):
        raise ValueError(
            "Use an absolute calendar period (for example July 2018); "
            "relative and fiscal periods are not supported."
        )

    natural_days = list(_NATURAL_DAY.finditer(question))
    iso_days = list(_ISO_DAY.finditer(question))
    natural_months = list(_NATURAL_MONTH.finditer(question))
    iso_months = list(_ISO_MONTH.finditer(question))
    years = list(_YEAR.finditer(question))

    # An ISO date contains its own month and year. A natural-language day
    # contains a year. Don't count those nested captures as extra periods.
    candidates = []
    occupied = []

    for match in natural_days:
        month, day, year = match.groups()
        value = date(int(year), _MONTHS[month.lower()[:3]], int(day))
        candidates.append((value.isoformat(), value.isoformat()))
        occupied.append(match.span())
    for match in iso_days:
        if any(match.start() < b and match.end() > a for a, b in occupied):
            continue
        year, month, day = map(int, match.groups())
        value = date(year, month, day)
        candidates.append((value.isoformat(), value.isoformat()))
        occupied.append(match.span())
    for match in natural_months:
        if any(match.start() < b and match.end() > a for a, b in occupied):
            continue
        month, year = match.groups()
        y, m = int(year), _MONTHS[month.lower()[:3]]
        candidates.append((date(y, m, 1).isoformat(),
                           date(y, m, calendar.monthrange(y, m)[1]).isoformat()))
        occupied.append(match.span())
    for match in iso_months:
        if any(match.start() < b and match.end() > a for a, b in occupied):
            continue
        y, m = map(int, match.groups())
        start = date(y, m, 1)
        candidates.append((start.isoformat(),
                           date(y, m, calendar.monthrange(y, m)[1]).isoformat()))
        occupied.append(match.span())
    for match in years:
        if any(match.start() < b and match.end() > a for a, b in occupied):
            continue
        year = int(match.group(1))
        candidates.append((f"{year}-01-01", f"{year}-12-31"))

    if len(candidates) > 1:
        raise ValueError(
            "More than one calendar period was mentioned. "
            "Please ask for one period at a time or use explicit date filters."
        )
    return candidates[0] if candidates else None
