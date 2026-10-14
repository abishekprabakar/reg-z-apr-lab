"""Tests for reg-z-apr-lab.

Every expected value comes from outside the solver: closed-form annuity
factors, hand-counted calendar intervals, or an independent bisection on the
textbook annuity formula. Nothing here is a snapshot of the library's output.
"""
import unittest
from datetime import date, timedelta

from regzapr import (
    CashFlow,
    apr_within_tolerance,
    build_disclosure,
    compute_apr,
    determine_unit_period,
    finance_charge_within_tolerance,
    is_regular,
    level_payment,
    measure,
    monthly_schedule,
)
from regzapr.schedule import UnitPeriod, add_months

MONTHLY = UnitPeriod("month", 1, 12.0)


def annuity_factor(r: float, n: int) -> float:
    """Present value of 1 per period for n periods: closed form."""
    return (1 - (1 + r) ** -n) / r


def bisect(f, lo: float, hi: float, iters: int = 200) -> float:
    """Plain bisection, deliberately independent of the library's Newton solver."""
    flo = f(lo)
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        fm = f(mid)
        if (fm > 0) == (flo > 0):
            lo, flo = mid, fm
        else:
            hi = mid
    return 0.5 * (lo + hi)


class CalendarTests(unittest.TestCase):
    def test_add_months_clamps_and_restores_anchor_day(self):
        self.assertEqual(add_months(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(add_months(date(2026, 2, 28), 1, anchor_day=31), date(2026, 3, 31))
        self.assertEqual(add_months(date(2024, 1, 31), 1), date(2024, 2, 29))  # leap year
        self.assertEqual(add_months(date(2026, 1, 15), -2), date(2025, 11, 15))

    def test_odd_first_period_hand_count(self):
        # Jan 10 -> Mar 1: count back one month to Feb 1, leaving Jan 10 -> Feb 1 = 22 days.
        self.assertEqual(measure(date(2026, 1, 10), date(2026, 3, 1), MONTHLY), (1, 22 / 30))
        self.assertEqual(measure(date(2026, 1, 10), date(2026, 4, 1), MONTHLY), (2, 22 / 30))

    def test_whole_months_have_no_fraction(self):
        self.assertEqual(measure(date(2026, 1, 1), date(2026, 2, 1), MONTHLY), (1, 0.0))
        self.assertEqual(measure(date(2026, 1, 1), date(2027, 1, 1), MONTHLY), (12, 0.0))

    def test_month_end_counting(self):
        # Month-end to month-end is whole months even through February.
        self.assertEqual(measure(date(2026, 1, 31), date(2026, 2, 28), MONTHLY), (1, 0.0))
        self.assertEqual(measure(date(2026, 1, 31), date(2026, 3, 31), MONTHLY), (2, 0.0))
        # Mar 31 back to Feb 28 back to Jan 31; Jan 15 -> Jan 31 is 16 odd days.
        self.assertEqual(measure(date(2026, 1, 15), date(2026, 3, 31), MONTHLY), (2, 16 / 30))

    def test_day_based_fraction(self):
        weekly = UnitPeriod("day", 7, 52.0)
        self.assertEqual(measure(date(2026, 6, 1), date(2026, 6, 11), weekly), (1, 3 / 7))

    def test_flow_before_start_rejected(self):
        with self.assertRaises(ValueError):
            measure(date(2026, 2, 1), date(2026, 1, 1), MONTHLY)


class UnitPeriodTests(unittest.TestCase):
    def test_monthly_with_odd_first_period(self):
        u = determine_unit_period(date(2026, 1, 10), monthly_schedule(date(2026, 3, 1), 100, 12))
        self.assertEqual((u.kind, u.length, u.periods_per_year), ("month", 1, 12.0))

    def test_quarterly(self):
        pays = [CashFlow(add_months(date(2026, 4, 1), 3 * k), 100) for k in range(8)]
        u = determine_unit_period(date(2026, 1, 1), pays)
        self.assertEqual((u.kind, u.length, u.periods_per_year), ("month", 3, 4.0))

    def test_weekly_and_biweekly_use_52_and_26(self):
        s = date(2026, 6, 1)
        wk = [CashFlow(s + timedelta(weeks=k + 1), 10) for k in range(10)]
        bw = [CashFlow(s + timedelta(weeks=2 * (k + 1)), 10) for k in range(10)]
        self.assertEqual(determine_unit_period(s, wk).periods_per_year, 52.0)
        self.assertEqual(determine_unit_period(s, bw).periods_per_year, 26.0)

    def test_most_common_interval_wins(self):
        pays = monthly_schedule(date(2026, 2, 1), 100, 12)
        pays[5] = CashFlow(pays[5].when + timedelta(days=9), 100)  # one late-scheduled payment
        u = determine_unit_period(date(2026, 1, 1), pays)
        self.assertEqual((u.kind, u.length), ("month", 1))

    def test_single_payment_unit_is_the_term(self):
        u = determine_unit_period(date(2026, 1, 1), [CashFlow(date(2026, 1, 15), 1)])
        self.assertEqual(u.length, 14)
        self.assertAlmostEqual(u.periods_per_year, 365 / 14, places=12)


class APRTests(unittest.TestCase):
    def test_level_annuity_recovers_note_rate(self):
        # 1% a month, 12 months: the payment is 1000 / a_12(1%), so APR must be 12%.
        pmt = 1000 / annuity_factor(0.01, 12)
        r = compute_apr([CashFlow(date(2026, 1, 1), 1000)], monthly_schedule(date(2026, 2, 1), pmt, 12))
        self.assertAlmostEqual(r.apr, 0.12, places=11)
        self.assertEqual(r.disclosed(), "12.00%")

    def test_payday_fee_is_391_percent(self):
        # $15 per $100 for 14 days: i = 0.15, 365/14 periods a year -> 391.07%.
        r = compute_apr([CashFlow(date(2026, 10, 1), 300)], [CashFlow(date(2026, 10, 15), 345)])
        self.assertAlmostEqual(r.rate_per_period, 0.15, places=12)
        self.assertAlmostEqual(r.apr, 0.15 * 365 / 14, places=12)
        self.assertEqual(r.disclosed(), "391.07%")

    def test_one_year_single_payment_is_simple_rate(self):
        r = compute_apr([CashFlow(date(2025, 1, 1), 100)], [CashFlow(date(2026, 1, 1), 110)])
        self.assertAlmostEqual(r.apr, 0.10, places=12)

    def test_odd_first_period_closed_form(self):
        # Every payment carries the same f = 22/30, so
        #   A = P * a_n(i) / (1 + f i)   =>   P = A (1 + f i) / a_n(i).
        i, n, A, f = 0.006, 36, 10_000.0, 22 / 30
        P = A * (1 + f * i) / annuity_factor(i, n)
        r = compute_apr([CashFlow(date(2026, 1, 10), A)], monthly_schedule(date(2026, 3, 1), P, n))
        self.assertAlmostEqual(r.rate_per_period, i, places=12)
        self.assertAlmostEqual(r.apr, 12 * i, places=11)

    def test_multiple_advances_closed_form(self):
        # Advances of A0 at t=0 and A1 at t=6, 12 level payments at 1%/month:
        #   A0 + A1 / 1.01^6 = P * a_12(1%).
        i, P, A0 = 0.01, 900.0, 5_000.0
        A1 = (P * annuity_factor(i, 12) - A0) * (1 + i) ** 6
        start = date(2026, 1, 1)
        r = compute_apr([CashFlow(start, A0), CashFlow(add_months(start, 6), A1)],
                        monthly_schedule(date(2026, 2, 1), P, 12))
        self.assertAlmostEqual(r.rate_per_period, i, places=12)

    def test_actuarial_balance_walk_ends_at_zero(self):
        # Independent check of the auto loan: walk the balance under the
        # actuarial method with the solved rate; it must amortise to zero.
        A = 25_000.0
        P = round(level_payment(A, 0.07 / 12, 60), 2)
        pays = monthly_schedule(date(2026, 3, 1), P, 60)
        i = compute_apr([CashFlow(date(2026, 1, 10), A)], pays).rate_per_period
        bal = A * (1 + 22 / 30 * i) * (1 + i) - P
        for _ in range(59):
            bal = bal * (1 + i) - P
        self.assertAlmostEqual(bal, 0.0, places=6)

    def test_extreme_rate_and_balloon_converge(self):
        start = date(2026, 1, 1)
        # 20% a month for 6 months.
        pmt = 1000 / annuity_factor(0.20, 6)
        r = compute_apr([CashFlow(start, 1000)], monthly_schedule(date(2026, 2, 1), pmt, 6))
        self.assertAlmostEqual(r.apr, 2.40, places=10)
        # Interest-only at 0.5%/month with a balloon: rate must be exactly 0.5%.
        pays = monthly_schedule(date(2026, 2, 1), 500.0, 60, final_amount=100_500.0)
        r = compute_apr([CashFlow(start, 100_000)], pays)
        self.assertAlmostEqual(r.rate_per_period, 0.005, places=12)

    def test_zero_finance_charge_is_zero_apr(self):
        r = compute_apr([CashFlow(date(2026, 1, 1), 1200)], monthly_schedule(date(2026, 2, 1), 100, 12))
        self.assertEqual(r.apr, 0.0)

    def test_payments_below_advance_rejected(self):
        with self.assertRaises(ValueError):
            compute_apr([CashFlow(date(2026, 1, 1), 1200)], monthly_schedule(date(2026, 2, 1), 90, 12))

    def test_negative_amount_rejected(self):
        with self.assertRaises(ValueError):
            CashFlow(date(2026, 1, 1), -5)


class DisclosureTests(unittest.TestCase):
    def test_points_raise_apr_above_note_rate(self):
        note, rate, n = 300_000.0, 0.065, 360
        P = round(level_payment(note, rate / 12, n), 2)
        prepaid = 7_495.0
        d = build_disclosure(note, monthly_schedule(date(2026, 3, 1), P, n),
                             closing=date(2026, 2, 1), prepaid_finance_charges=prepaid)
        af = note - prepaid
        self.assertAlmostEqual(d.amount_financed, af, places=2)
        self.assertAlmostEqual(d.total_of_payments, round(P * n, 2), places=2)
        self.assertAlmostEqual(d.finance_charge, round(P * n - af, 2), places=2)
        # Independent: bisect P * a_360(r) = amount financed.
        r = bisect(lambda x: P * annuity_factor(x, n) - af, 1e-6, 0.05)
        self.assertAlmostEqual(d.apr.apr, 12 * r, places=10)
        self.assertGreater(d.apr.apr, rate)
        self.assertTrue(d.regular)

    def test_apr_tolerance_regular_vs_irregular(self):
        self.assertTrue(apr_within_tolerance(0.0631, 0.0619, regular=True))   # 0.12 pt
        self.assertFalse(apr_within_tolerance(0.0632, 0.0619, regular=True))  # 0.13 pt
        self.assertTrue(apr_within_tolerance(0.0643, 0.0619, regular=False))  # 0.24 pt
        self.assertFalse(apr_within_tolerance(0.0645, 0.0619, regular=False)) # 0.26 pt
        self.assertTrue(apr_within_tolerance(0.0619 - 0.00125, 0.0619, regular=True))  # boundary

    def test_finance_charge_tolerance(self):
        # Dwelling-secured: understatement up to $100, any overstatement.
        self.assertTrue(finance_charge_within_tolerance(9_900, 10_000, 200_000, True))
        self.assertFalse(finance_charge_within_tolerance(9_899.99, 10_000, 200_000, True))
        self.assertTrue(finance_charge_within_tolerance(15_000, 10_000, 200_000, True))
        # Other loans: $5 at or below $1,000 financed, $10 above.
        self.assertTrue(finance_charge_within_tolerance(95, 100, 1_000, False))
        self.assertFalse(finance_charge_within_tolerance(94.99, 100, 1_000, False))
        self.assertTrue(finance_charge_within_tolerance(90, 100, 1_000.01, False))
        self.assertFalse(finance_charge_within_tolerance(89.99, 100, 1_000.01, False))

    def test_regular_transaction_classification(self):
        adv = [CashFlow(date(2026, 1, 10), 1000)]
        pays = monthly_schedule(date(2026, 3, 1), 100, 12, final_amount=37.12)
        pays[0] = CashFlow(pays[0].when, 120)  # odd first payment is still regular
        self.assertTrue(is_regular(adv, pays))
        self.assertFalse(is_regular(adv + [CashFlow(date(2026, 2, 1), 500)], pays))
        skipped = [p for k, p in enumerate(pays) if k != 6]  # a skip-a-payment month
        self.assertFalse(is_regular(adv, skipped))
        uneven = list(pays)
        uneven[4] = CashFlow(uneven[4].when, 150)
        self.assertFalse(is_regular(adv, uneven))

    def test_construction_draws_are_irregular_with_extra_advances(self):
        start = date(2026, 1, 1)
        draws = [CashFlow(add_months(start, 2), 60_000), CashFlow(add_months(start, 5), 60_000)]
        pays = monthly_schedule(date(2026, 2, 1), 1_000.0, 12, final_amount=201_000.0)
        d = build_disclosure(200_000, pays, closing=start, prepaid_finance_charges=2_500, extra_advances=draws)
        self.assertFalse(d.regular)
        self.assertAlmostEqual(d.amount_financed, 197_500.0)
        self.assertAlmostEqual(d.finance_charge, 11 * 1_000 + 201_000 - 197_500)
        self.assertIn("ANNUAL PERCENTAGE RATE", d.render())

    def test_bad_prepaid_rejected(self):
        with self.assertRaises(ValueError):
            build_disclosure(1000, monthly_schedule(date(2026, 2, 1), 100, 12), date(2026, 1, 1), prepaid_finance_charges=1000)


if __name__ == "__main__":
    unittest.main()
