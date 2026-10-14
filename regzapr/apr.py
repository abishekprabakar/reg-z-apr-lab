"""The Appendix J general equation and its solver.

For advances A_k and payments P_j measured from the start of the term,

    sum_k  A_k / ((1 + f_k*i) * (1 + i)**t_k)
  = sum_j  P_j / ((1 + f_j*i) * (1 + i)**t_j)

where i is the rate per unit period. The APR is i times the number of unit
periods in a year (Appendix J (b)(8): the APR is the nominal rate, not the
effective one).

The present value of the payments is strictly decreasing in i while the
advances (usually all at t=0) change more slowly, so the equation has one
root on (-1, inf) whenever total payments exceed total advances. The solver
brackets that root and then runs safeguarded Newton (bisection whenever a
Newton step would leave the bracket), so it converges for odd periods,
multiple advances and balloon payments alike.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Sequence, Tuple

from .schedule import CashFlow, UnitPeriod, determine_unit_period, flows_by_period

Measured = List[Tuple[float, int, float]]


def _pv(flows: Measured, i: float) -> Tuple[float, float]:
    """Present value of measured flows at rate i, and its derivative in i."""
    total = 0.0
    deriv = 0.0
    for amount, t, f in flows:
        simple = 1.0 + f * i
        compound = (1.0 + i) ** t
        denom = simple * compound
        total += amount / denom
        # d/di [ 1 / ((1+fi)(1+i)^t) ] = -(f/(1+fi) + t/(1+i)) / denom
        deriv -= amount * (f / simple + t / (1.0 + i)) / denom
    return total, deriv


def solve_rate(advances: Measured, payments: Measured, tol: float = 1e-13, max_iter: int = 200) -> float:
    """Rate per unit period that balances the general equation."""
    total_adv = sum(a for a, _, _ in advances)
    total_pay = sum(p for p, _, _ in payments)
    if total_adv <= 0:
        raise ValueError("there must be at least one positive advance")
    if abs(total_pay - total_adv) <= 1e-12 * max(total_adv, 1.0):
        return 0.0
    if total_pay < total_adv:
        raise ValueError("payments total less than the amount financed; there is no finance charge to annualise")

    def g(i: float) -> Tuple[float, float]:
        pa, da = _pv(advances, i)
        pp, dp = _pv(payments, i)
        return pa - pp, da - dp

    lo, hi = 0.0, 0.01
    while g(hi)[0] < 0.0:
        lo, hi = hi, hi * 2.0
        if hi > 1e6:
            raise ArithmeticError("could not bracket the APR")

    x = 0.5 * (lo + hi)
    for _ in range(max_iter):
        val, d = g(x)
        if val > 0:
            hi = x
        else:
            lo = x
        step_ok = d != 0.0
        nx = x - val / d if step_ok else lo - 1.0
        if not (lo < nx < hi):
            nx = 0.5 * (lo + hi)
        if abs(nx - x) <= tol * max(1.0, abs(x)):
            return nx
        x = nx
    raise ArithmeticError("APR solver did not converge")


@dataclass(frozen=True)
class APRResult:
    apr: float                    # nominal annual rate as a fraction, e.g. 0.0619
    rate_per_period: float
    unit: UnitPeriod
    advances: Measured
    payments: Measured

    @property
    def apr_percent(self) -> float:
        return 100.0 * self.apr

    def disclosed(self) -> str:
        """APR rounded the way it is printed on a TILA disclosure."""
        return f"{self.apr_percent:.2f}%"


def compute_apr(
    advances: Sequence[CashFlow],
    payments: Sequence[CashFlow],
    start: Optional[date] = None,
    unit: Optional[UnitPeriod] = None,
) -> APRResult:
    """Compute the Reg Z APR for an arbitrary closed-end schedule.

    ``start`` defaults to the earliest advance (the beginning of the term).
    ``unit`` defaults to the Appendix J choice from the payment intervals.
    """
    if not advances or not payments:
        raise ValueError("need at least one advance and one payment")
    start = start or min(a.when for a in advances)
    unit = unit or determine_unit_period(start, payments)
    adv = flows_by_period(start, advances, unit)
    pay = flows_by_period(start, payments, unit)
    i = solve_rate(adv, pay)
    return APRResult(apr=i * unit.periods_per_year, rate_per_period=i, unit=unit, advances=adv, payments=pay)
