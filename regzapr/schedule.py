"""Cash-flow schedules and Appendix J time measurement.

Regulation Z, Appendix J measures every advance and every payment from the
beginning of the term as a whole number of *unit periods* ``t`` plus a
fraction ``f`` of a unit period. Full unit periods are counted backward from
the cash-flow date toward the start of the term; whatever is left over is the
fraction, and it sits at the *beginning* of the interval. That placement is
why the general equation discounts each flow by

    (1 + f*i) * (1 + i)**t

-- simple interest over the odd fraction, compound interest over full periods.

Conventions implemented here (Appendix J (b)(3)-(b)(5)):

* Unit period = the most common interval between scheduled payments
  (the first period is ignored when choosing it, because it is the one most
  often irregular). Calendar-month multiples are measured in months; anything
  else in days.
* A transaction with a single payment uses the whole term as its unit period
  (capped at one year).
* Fractions of a month-based unit period use 30-day months (permitted by
  (b)(5)(iv)); day-based unit periods divide leftover days by the period
  length.
* Periods per year: 12/k for a k-month unit, 52 for weekly, 26 for biweekly,
  365/d for any other d-day unit, and 365/term for a single-payment loan.
"""
from __future__ import annotations

import calendar
from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Iterable, List, Sequence, Tuple


@dataclass(frozen=True)
class CashFlow:
    """A dated amount. Advances are flows to the borrower, payments from."""

    when: date
    amount: float

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise ValueError("cash-flow amounts are positive; direction comes from the list")


@dataclass(frozen=True)
class UnitPeriod:
    """The Appendix J unit period.

    kind is "month" (length counted in calendar months) or "day".
    """

    kind: str
    length: int
    periods_per_year: float

    @property
    def fraction_days(self) -> int:
        """Days in one unit period when measuring an odd fraction."""
        return 30 * self.length if self.kind == "month" else self.length

    def describe(self) -> str:
        if self.kind == "month":
            names = {1: "monthly", 3: "quarterly", 6: "semiannual", 12: "annual"}
            return names.get(self.length, f"{self.length}-month")
        names = {7: "weekly", 14: "biweekly"}
        return names.get(self.length, f"{self.length}-day")


def _is_month_end(d: date) -> bool:
    return d.day == calendar.monthrange(d.year, d.month)[1]


def add_months(d: date, months: int, anchor_day: int | None = None, month_end: bool = False) -> date:
    """Shift ``d`` by whole months, clamping to the length of the target month.

    ``anchor_day`` keeps the original day-of-month across short months
    (Jan 31 -> Feb 28 -> Mar 31), and ``month_end`` pins to the last day.
    """
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    last = calendar.monthrange(year, month)[1]
    if month_end:
        return date(year, month, last)
    day = anchor_day if anchor_day is not None else d.day
    return date(year, month, min(day, last))


def months_between(a: date, b: date) -> int | None:
    """Whole calendar months from a to b if b is exactly that many months on.

    Returns None when the interval is not a whole number of months.
    Month-end to month-end counts as whole months (Jan 31 -> Feb 28).
    """
    n = (b.year - a.year) * 12 + (b.month - a.month)
    if n <= 0:
        return None
    if add_months(a, n, month_end=_is_month_end(a) and _is_month_end(b)) == b:
        return n
    return None


def determine_unit_period(start: date, payments: Sequence[CashFlow]) -> UnitPeriod:
    """Choose the unit period per Appendix J (b)(3)."""
    if not payments:
        raise ValueError("a schedule needs at least one payment")
    dates = sorted(p.when for p in payments)

    if len(dates) == 1:
        days = (dates[0] - start).days
        if days <= 0:
            raise ValueError("the single payment must fall after the start of the term")
        days = min(days, 365)
        # The term itself is the unit period, so it recurs 365/term times a year.
        return UnitPeriod("day", days, 365.0 / days)

    gaps: List[Tuple[str, int]] = []
    for a, b in zip(dates, dates[1:]):
        m = months_between(a, b)
        gaps.append(("month", m) if m is not None else ("day", (b - a).days))

    counts = Counter(gaps)
    # most_common is stable for ties; prefer the earliest-seen interval.
    (kind, length), _ = counts.most_common(1)[0]
    if length <= 0:
        raise ValueError("two payments fall on the same date")
    if kind == "month":
        return UnitPeriod("month", length, 12.0 / length)
    return _day_unit(length)


def _day_unit(days: int) -> UnitPeriod:
    per_year = {7: 52.0, 14: 26.0}.get(days, 365.0 / days)
    return UnitPeriod("day", days, per_year)


def measure(start: date, when: date, unit: UnitPeriod) -> Tuple[int, float]:
    """Return (t, f): full unit periods and leftover fraction from start to when.

    Full periods are counted backward from ``when``; the remainder is at the
    beginning of the interval, per Appendix J (b)(5).
    """
    if when < start:
        raise ValueError(f"{when} is before the start of the term {start}")

    if unit.kind == "day":
        days = (when - start).days
        t, rem = divmod(days, unit.length)
        return t, rem / unit.length

    month_end = _is_month_end(when)
    t = 0
    cursor = when
    while True:
        prev = add_months(when, -(t + 1) * unit.length, anchor_day=when.day, month_end=month_end)
        if prev < start:
            break
        t += 1
        cursor = prev
    leftover_days = (cursor - start).days
    return t, leftover_days / unit.fraction_days


def flows_by_period(start: date, flows: Iterable[CashFlow], unit: UnitPeriod) -> List[Tuple[float, int, float]]:
    """Map each flow to (amount, t, f)."""
    return [(cf.amount, *measure(start, cf.when, unit)) for cf in flows]
