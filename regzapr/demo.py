"""Worked examples: python -m regzapr.demo"""
from __future__ import annotations

from datetime import date, timedelta

from .apr import compute_apr
from .disclosure import (
    apr_within_tolerance,
    build_disclosure,
    finance_charge_within_tolerance,
    level_payment,
    monthly_schedule,
)
from .schedule import CashFlow, add_months


def banner(title: str) -> None:
    print()
    print("=" * 124)
    print(title)
    print("=" * 124)


def auto_loan() -> None:
    banner("1. Auto loan with an odd first period: $25,000 at a 7.00% note rate, 60 months, signed Jan 10, first payment Mar 1")
    pmt = round(level_payment(25_000, 0.07 / 12, 60), 2)
    pays = monthly_schedule(date(2026, 3, 1), pmt, 60)
    d = build_disclosure(25_000, pays, closing=date(2026, 1, 10))
    print(d.render())
    amt, t, f = d.apr.payments[0]
    print(f"  first payment measured as t={t} full month(s) + f={f:.4f} (22 odd days / 30): the borrower")
    print("  makes a payment sized for an ordinary 1-month first period yet holds the money for 50 days,")
    print("  and no odd-days interest is collected, so the APR lands BELOW the 7.00% note rate")


def mortgage_with_points() -> None:
    banner("2. Mortgage with points: $300,000 note at 6.50%, 30 years, 2 points + $1,495 origination")
    note = 300_000
    pmt = round(level_payment(note, 0.065 / 12, 360), 2)
    pays = monthly_schedule(date(2026, 3, 1), pmt, 360)
    prepaid = 0.02 * note + 1_495
    d = build_disclosure(note, pays, closing=date(2026, 2, 1), prepaid_finance_charges=prepaid)
    print(d.render())

    print()
    print("  Checking three hypothetical lender disclosures against 1026.22(a)(2) and 1026.18(d)(1):")
    true_apr, true_fc = d.apr.apr, d.finance_charge
    for label, apr, fc in (
        ("ignores the $1,495 fee", 0.0670, true_fc - 1_495),
        ("rounded down by 0.1 pt", true_apr - 0.0010, true_fc - 60),
        ("quotes the note rate", 0.0650, true_fc - 7_495),
    ):
        ok_apr = apr_within_tolerance(apr, true_apr, d.regular)
        ok_fc = finance_charge_within_tolerance(fc, true_fc, d.amount_financed, dwelling_secured=True)
        print(f"    {label:<24} APR {100*apr:6.3f}% -> {'ok  ' if ok_apr else 'FAIL'}   "
              f"FC ${fc:>12,.2f} -> {'ok' if ok_fc else 'FAIL (understated by $' + format(true_fc - fc, ',.2f') + ')'}")


def payday() -> None:
    banner("3. Single-payment loan: $300 advanced, $345 due in 14 days")
    r = compute_apr([CashFlow(date(2026, 10, 1), 300)], [CashFlow(date(2026, 10, 15), 345)])
    print(f"  unit period = the term ({r.unit.describe()}, {r.unit.periods_per_year:g}/yr); "
          f"rate per period {r.rate_per_period:.4%}; APR {r.disclosed()}")
    print("  A '$15 per $100' fee is a 391% APR because the fee recurs 26 times a year.")


def construction_loan() -> None:
    banner("4. Construction draws then a balloon: irregular transaction, multiple advances")
    start = date(2026, 1, 1)
    draws = [CashFlow(add_months(start, k), amt) for k, amt in ((0, 80_000), (2, 60_000), (5, 60_000))]
    interest_only = [CashFlow(add_months(start, k), 1_000.0) for k in range(1, 12)]
    balloon = [CashFlow(add_months(start, 12), 200_000 + 1_000)]
    note = 200_000
    d = build_disclosure(note, interest_only + balloon, closing=start,
                         prepaid_finance_charges=2_500, extra_advances=draws[1:])
    print(d.render())
    print("  draws: " + ", ".join(f"${a.amount:,.0f} on {a.when}" for a in draws)
          + "  (the $2,500 fee comes out of the first draw)")


def weekly_rent_to_own() -> None:
    banner("5. Weekly payments: $1,200 TV, 78 weekly payments of $25")
    start = date(2026, 6, 5)
    pays = [CashFlow(start + timedelta(weeks=k + 1), 25.0) for k in range(78)]
    r = compute_apr([CashFlow(start, 1_200)], pays)
    print(f"  unit period {r.unit.describe()} ({r.unit.periods_per_year:g}/yr); APR {r.disclosed()}; "
          f"total of payments ${78*25:,.2f}")


def main() -> None:
    auto_loan()
    mortgage_with_points()
    payday()
    construction_loan()
    weekly_rent_to_own()
    print()


if __name__ == "__main__":
    main()
