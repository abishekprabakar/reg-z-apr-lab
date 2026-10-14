# reg-z-apr-lab

The annual percentage rate the way Regulation Z actually defines it: the
Appendix J general equation, solved for any closed-end schedule — odd first
periods, points and fees, multiple advances, balloons, weekly or single-payment
loans — and checked against the 12 CFR 1026.22 and 1026.18(d) accuracy
tolerances. Pure Python, standard library only.

## Why this is not just "solve for the rate of an annuity"

* **Odd periods.** Appendix J counts *full unit periods backward* from each
  payment date and leaves the remainder at the start of the term, where it
  earns *simple* interest. Every flow is discounted by `(1 + f·i)(1 + i)^t`,
  not `(1 + i)^(t+f)`. A loan signed Jan 10 with a first payment on Mar 1 has
  `t = 1`, `f = 22/30` for that payment.
* **The unit period comes from the schedule.** It is the most common interval
  between payments (monthly, quarterly, weekly = 52/yr, biweekly = 26/yr…); a
  single-payment loan uses its whole term, which is how a $15-per-$100,
  14-day loan becomes **391.07%**.
* **APR is on the amount financed.** Points and origination fees are prepaid
  finance charges: the payment is sized on the note, the borrower receives
  less, so the APR sits above the note rate.
* **Month-end arithmetic.** Jan 31 → Feb 28 → Mar 31 are whole months.
* **Tolerances.** An APR is accurate within 1/8 point for a *regular*
  transaction and 1/4 point for an *irregular* one (multiple advances,
  uneven intervals or amounts). A finance charge on a dwelling-secured loan is
  accurate if understated by no more than $100; on other loans, $5 (amount
  financed ≤ $1,000) or $10. Overstatement is always tolerated.

## Layout

| File | What it does |
|---|---|
| `regzapr/schedule.py` | Cash flows, Appendix J unit-period choice, backward period counting, month-end handling |
| `regzapr/apr.py` | The general equation with an analytic derivative; bracketed, safeguarded Newton solver |
| `regzapr/disclosure.py` | TILA four-box disclosure, regular/irregular classification, APR and finance-charge tolerances |
| `regzapr/demo.py` | Five worked loans |
| `tests/test_regzapr.py` | 27 tests |

## Run it

```bash
python3 -m regzapr.demo
python3 -m unittest discover -s tests -v
```

```python
from datetime import date
from regzapr import CashFlow, compute_apr
r = compute_apr([CashFlow(date(2026, 10, 1), 300)], [CashFlow(date(2026, 10, 15), 345)])
print(r.disclosed())   # 391.07%
```

## How the tests know the right answer

No expected value is copied from the solver's own output:

* level annuities rebuilt from the closed-form factor `a_n(i)` must give back
  exactly `12·i` (e.g. 1%/month → 12.00%);
* an odd first period where every payment shares `f = 22/30` has the closed
  form `P = A(1 + f·i)/a_n(i)`;
* two advances (month 0 and month 6) are constructed so that
  `A0 + A1/1.01^6 = P·a_12(1%)`;
* the points-and-fees mortgage APR is cross-checked by an independent
  bisection on the textbook annuity formula;
* the auto loan is re-amortised by an actuarial balance walk that must end at
  zero;
* calendar counts (22 odd days, 16 odd days to a month end) are hand-counted;
* the tolerance boundaries ($100, $5/$10, 1/8 and 1/4 point) are probed on
  both sides.

Six hand-made mutants (31-day months, 365/14 for biweekly, a 1/8-point
irregular tolerance, compound instead of simple odd-period interest, `<`
instead of `≤` on the $1,000 threshold, an off-by-one in backward counting)
are each caught by at least one test.

## Sample output (`python3 -m regzapr.demo`)

```

============================================================================================================================
1. Auto loan with an odd first period: $25,000 at a 7.00% note rate, 60 months, signed Jan 10, first payment Mar 1
============================================================================================================================
+---------------------------------------------------------------------------------------------------------------------------+
|    ANNUAL PERCENTAGE RATE    |        FINANCE CHARGE        |       Amount Financed        |      Total of Payments       |
|            6.83%             |          $4,701.80           |          $25,000.00          |          $29,701.80          |
+---------------------------------------------------------------------------------------------------------------------------+
  unit period: monthly  (12/yr), rate per period 0.00568788
  note amount $25,000.00, prepaid finance charges $0.00
  transaction is regular (1/8 pt APR tolerance)
    60 payment(s) of $495.03 starting 2026-03-01
  first payment measured as t=1 full month(s) + f=0.7333 (22 odd days / 30): the borrower
  makes a payment sized for an ordinary 1-month first period yet holds the money for 50 days,
  and no odd-days interest is collected, so the APR lands BELOW the 7.00% note rate

============================================================================================================================
2. Mortgage with points: $300,000 note at 6.50%, 30 years, 2 points + $1,495 origination
============================================================================================================================
+---------------------------------------------------------------------------------------------------------------------------+
|    ANNUAL PERCENTAGE RATE    |        FINANCE CHARGE        |       Amount Financed        |      Total of Payments       |
|            6.74%             |         $390,127.00          |         $292,505.00          |         $682,632.00          |
+---------------------------------------------------------------------------------------------------------------------------+
  unit period: monthly  (12/yr), rate per period 0.00562079
  note amount $300,000.00, prepaid finance charges $7,495.00
  transaction is regular (1/8 pt APR tolerance)
   360 payment(s) of $1,896.20 starting 2026-03-01

  Checking three hypothetical lender disclosures against 1026.22(a)(2) and 1026.18(d)(1):
    ignores the $1,495 fee   APR  6.700% -> ok     FC $  388,632.00 -> FAIL (understated by $1,495.00)
    rounded down by 0.1 pt   APR  6.645% -> ok     FC $  390,067.00 -> ok
    quotes the note rate     APR  6.500% -> FAIL   FC $  382,632.00 -> FAIL (understated by $7,495.00)

============================================================================================================================
3. Single-payment loan: $300 advanced, $345 due in 14 days
============================================================================================================================
  unit period = the term (biweekly, 26.0714/yr); rate per period 15.0000%; APR 391.07%
  A '$15 per $100' fee is a 391% APR because the fee recurs 26 times a year.

============================================================================================================================
4. Construction draws then a balloon: irregular transaction, multiple advances
============================================================================================================================
+---------------------------------------------------------------------------------------------------------------------------+
|    ANNUAL PERCENTAGE RATE    |        FINANCE CHARGE        |       Amount Financed        |      Total of Payments       |
|            8.92%             |          $14,500.00          |         $197,500.00          |         $212,000.00          |
+---------------------------------------------------------------------------------------------------------------------------+
  unit period: monthly  (12/yr), rate per period 0.00743113
  note amount $200,000.00, prepaid finance charges $2,500.00
  transaction is irregular (1/4 pt APR tolerance)
    11 payment(s) of $1,000.00 starting 2026-02-01
     1 payment(s) of $201,000.00 starting 2027-01-01
  draws: $80,000 on 2026-01-01, $60,000 on 2026-03-01, $60,000 on 2026-06-01  (the $2,500 fee comes out of the first draw)

============================================================================================================================
5. Weekly payments: $1,200 TV, 78 weekly payments of $25
============================================================================================================================
  unit period weekly (52/yr); APR 70.36%; total of payments $1,950.00

```

Tests:

```
$ python3 -m unittest discover -s tests
...........................
Ran 27 tests in 0.084s

OK
```

Note the auto loan: with no odd-days interest collected, a payment sized for a
normal first month but due 50 days after funding gives an APR *below* the note
rate. And in the mortgage check, leaving the $1,495 fee out moves the APR by
only 0.04 point — inside tolerance — while the finance charge is $1,495
understated, well past the $100 limit.

## Scope

Closed-end credit only. Not implemented: the United States Rule
method, open-end (1026.14) APRs, variable-rate composite
schedules, and private mortgage insurance. Not legal advice.

## License

MIT
