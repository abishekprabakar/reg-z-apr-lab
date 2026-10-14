"""Building a closed-end TILA disclosure and checking it against Reg Z tolerances.

The four boxes of a closed-end disclosure (12 CFR 1026.18):

* Amount financed  = loan proceeds less prepaid finance charges
                     (points, origination and other lender fees paid at closing)
* Finance charge   = total of payments less amount financed
* Total of payments
* Annual percentage rate (computed on the amount financed, not the note amount)

That is why a mortgage with points has an APR above its note rate: the
borrower repays a payment stream sized on the full note while receiving less.

Tolerances:

* APR, 1026.22(a)(2)/(3): accurate if within 1/8 percentage point of the
  true APR for a *regular* transaction, 1/4 point for an *irregular* one
  (multiple advances, irregular payment periods or irregular amounts, other
  than an odd first period or an odd first/last payment).
* Finance charge, 1026.18(d)(1): for a dwelling-secured loan, accurate if
  understated by no more than $100, or overstated by any amount.
  1026.18(d)(2): otherwise, understated by no more than $5 when the amount
  financed is $1,000 or less, $10 when it is more; overstatement is fine.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Sequence

from .apr import APRResult, compute_apr
from .schedule import CashFlow, months_between

REGULAR_TOLERANCE = 0.00125   # 1/8 of a percentage point
IRREGULAR_TOLERANCE = 0.0025  # 1/4 of a percentage point


def is_regular(advances: Sequence[CashFlow], payments: Sequence[CashFlow]) -> bool:
    """Regular transaction per 1026.22(a)(2).

    One advance; payment intervals all equal except the first; payment amounts
    all equal except the first and last.
    """
    if len(advances) != 1:
        return False
    pays = sorted(payments, key=lambda p: p.when)
    if len(pays) <= 2:
        return True
    intervals = []
    for a, b in zip(pays, pays[1:]):
        m = months_between(a.when, b.when)
        intervals.append(("m", m) if m is not None else ("d", (b.when - a.when).days))
    if len(set(intervals)) != 1:
        return False
    middle = [round(p.amount, 2) for p in pays[1:-1]]
    return len(set(middle)) <= 1


def apr_within_tolerance(disclosed_apr: float, true_apr: float, regular: bool) -> bool:
    tol = REGULAR_TOLERANCE if regular else IRREGULAR_TOLERANCE
    return abs(disclosed_apr - true_apr) <= tol + 1e-12


def finance_charge_within_tolerance(disclosed: float, true: float, amount_financed: float, dwelling_secured: bool) -> bool:
    understated = true - disclosed
    if understated <= 0:
        return True
    if dwelling_secured:
        limit = 100.0
    else:
        limit = 5.0 if amount_financed <= 1000.0 else 10.0
    return understated <= limit + 1e-9


@dataclass
class Disclosure:
    note_amount: float
    prepaid_finance_charges: float
    amount_financed: float
    total_of_payments: float
    finance_charge: float
    apr: APRResult
    regular: bool
    payment_summary: List[str] = field(default_factory=list)

    def render(self) -> str:
        w = 30
        lines = [
            "+" + "-" * (w * 4 + 3) + "+",
            "|" + "|".join(h.center(w) for h in ("ANNUAL PERCENTAGE RATE", "FINANCE CHARGE", "Amount Financed", "Total of Payments")) + "|",
            "|" + "|".join(
                v.center(w)
                for v in (
                    self.apr.disclosed(),
                    f"${self.finance_charge:,.2f}",
                    f"${self.amount_financed:,.2f}",
                    f"${self.total_of_payments:,.2f}",
                )
            ) + "|",
            "+" + "-" * (w * 4 + 3) + "+",
        ]
        lines.append(f"  unit period: {self.apr.unit.describe()}  "
                     f"({self.apr.unit.periods_per_year:g}/yr), rate per period {self.apr.rate_per_period:.8f}")
        lines.append(f"  note amount ${self.note_amount:,.2f}, prepaid finance charges ${self.prepaid_finance_charges:,.2f}")
        lines.append(f"  transaction is {'regular (1/8 pt APR tolerance)' if self.regular else 'irregular (1/4 pt APR tolerance)'}")
        lines.extend("  " + s for s in self.payment_summary)
        return "\n".join(lines)


def summarise_payments(payments: Sequence[CashFlow]) -> List[str]:
    pays = sorted(payments, key=lambda p: p.when)
    out: List[str] = []
    run_amt, run_start, run_n = None, None, 0
    for p in pays + [None]:  # sentinel flushes the last run
        amt = round(p.amount, 2) if p else None
        if amt == run_amt:
            run_n += 1
            continue
        if run_amt is not None:
            out.append(f"{run_n:>4} payment(s) of ${run_amt:,.2f} starting {run_start.isoformat()}")
        if p:
            run_amt, run_start, run_n = amt, p.when, 1
    return out


def build_disclosure(
    note_amount: float,
    payments: Sequence[CashFlow],
    closing: date,
    prepaid_finance_charges: float = 0.0,
    extra_advances: Sequence[CashFlow] = (),
) -> Disclosure:
    """Build a TILA disclosure for a closed-end loan.

    The borrower receives ``note_amount - prepaid_finance_charges`` at
    ``closing`` (plus any ``extra_advances``, e.g. construction draws) and
    owes ``payments``.
    """
    if prepaid_finance_charges < 0 or prepaid_finance_charges >= note_amount:
        raise ValueError("prepaid finance charges must be in [0, note amount)")
    first = CashFlow(closing, note_amount - prepaid_finance_charges - sum(a.amount for a in extra_advances))
    advances = [first, *extra_advances]
    amount_financed = sum(a.amount for a in advances)
    total = sum(p.amount for p in payments)
    result = compute_apr(advances, payments, start=closing)
    return Disclosure(
        note_amount=note_amount,
        prepaid_finance_charges=prepaid_finance_charges,
        amount_financed=round(amount_financed, 2),
        total_of_payments=round(total, 2),
        finance_charge=round(total - amount_financed, 2),
        apr=result,
        regular=is_regular(advances, payments),
        payment_summary=summarise_payments(payments),
    )


def level_payment(principal: float, rate_per_period: float, n: int) -> float:
    """Closed-form annuity payment, unrounded."""
    if rate_per_period == 0:
        return principal / n
    r = rate_per_period
    return principal * r / (1.0 - (1.0 + r) ** -n)


def monthly_schedule(first_due: date, amount: float, n: int, final_amount: Optional[float] = None) -> List[CashFlow]:
    """n monthly payments starting at first_due, optional different final payment."""
    from .schedule import add_months

    pays = [CashFlow(add_months(first_due, k, anchor_day=first_due.day), amount) for k in range(n)]
    if final_amount is not None:
        pays[-1] = CashFlow(pays[-1].when, final_amount)
    return pays
