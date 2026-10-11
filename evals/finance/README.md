# Finance evals

Real church books are hard to read. Online gifts sit in Stripe for weeks, a fund balance
has not moved since anyone can remember, the main checking account is named like a heading,
a parsonage sale makes a deficit year look healthy. The first finance skill exists to help a
pastor or church administrator understand their own books, so these evals test it against
books like that.

Every church here is fictional and every figure is generated. None comes from a real church.

## The churches

Each file in `churches/` describes one church's books (`CHURCH`) and what a careful
bookkeeper would tell the pastor about them (`TRUTH`). `books.py` turns the description into
what Intuit's QuickBooks connector would return: a balance sheet split by month that always
balances, and a profit and loss for any period, in the connector's own shapes.

| Church | What makes the books hard to read |
|---|---|
| Cedar Hollow Lutheran | Fund accounting: the year closes into a fund balance each January. Account numbers with hyphen and letter parts. One heading holds most income. Frozen fund balances, one with gifts and costs still flowing. School payroll tax passing through. Storm damage and the insurance payment for it. |
| Millbrook Episcopal | Online gifts stuck in Stripe, so giving looks like it fell. A clearing account below zero. Undeposited Funds. Payroll liabilities and deferred rent below zero. Opening Balance Equity. Unsorted spending in Ask My Accountant. The connector restarting Net Income in August for a calendar-year church. Building equity labeled "Temporarily Restricted". No budget. |
| Stonegate Community | A deficit hidden by one-time money: a forgiven payroll loan, a retention credit, a bequest and a parsonage sale. A brokerage account filed among the banks. The main checking account named in capitals. A closed account with history. Legal fees under the building. A mortgage. No denomination. |
| Harbor Light Lutheran | Over a hundred profit and loss rows, past the connector's silent cutoff. |
| Lantern Hill Episcopal | A July-to-June year. A yearly insurance premium every July. Checking overdrawn at month end. |
| Wellspring Mission | Books that start in February. Most money in Uncategorized Income and Uncategorized Expense. |

## Two kinds of eval

**Scripts** (`score.py`, no model, no cost). Lays out each church's folder and pulls, runs
finance onboarding `look` and the finance report's `setup draft` and `build`, and checks
each result against `TRUTH["checks"]`. The test suite runs it on every change
(`tests/test_finance_evals.py`).

```bash
python3 evals/finance/score.py               # a table of every check
python3 evals/finance/score.py millbrook     # one church
```

A check with a `gap` note is a weakness we know about and have not fixed. It is expected to
fail. When a fix makes it pass, the test suite fails until the gap note is removed, so the
check then guards the fix.

**Skill runs** (`skill_eval.py`, Claude, costs money). Claude runs finance onboarding's first
stage as written, reading QuickBooks only through `quickbooks_stub.py`, a read-only stand-in
for the connector that serves the church's books and cuts off at 100 rows like the real one.
Nobody is at the keyboard, so the run writes its questions to a file. Then the grader:

- checks every dollar figure in the pastor's overview against the books: a figure that no
  balance, total or result supports is listed as unsupported;
- has a judge model read the overview against `TRUTH["skill"]`: what the pastor must be told,
  what must be asked of the treasurer, and what must never be said (stating a guess as fact,
  calling a fund-close entry a loss, counting an investment as cash);
- rates clarity: could the pastor say whether the church can pay its bills, which way the
  year is going, and what to ask the treasurer.

```bash
python3 evals/finance/skill_eval.py all --model claude-sonnet-5-5 --model claude-opus-5-5 \
  --out ~/handbuilt-runtime/finance-evals/$(date +%F)
python3 evals/finance/skill_eval.py table ~/handbuilt-runtime/finance-evals/$(date +%F)
```

This needs Claude Code signed in, so it runs on a computer with a model key, not in CI. Runs
and grades are test results: keep them outside this repository.

## Adding a church

1. Copy a church file, give it a new `id`, and describe the books. Invent every name and
   figure; never borrow from a real church's books, even reworded.
2. Write `TRUTH`: the everyday bank accounts, the one-time items, the checks, and the
   rubric. Mark a check you expect to fail today with a `gap` note in plain words.
3. Add it to `churches/__init__.py` and run `python3 evals/finance/score.py`.
4. Register any new account number in `tools/example-accounts.txt` and any written figure of
   1,000 or more in `tools/example-figures.txt`, then run `python3 tools/pii_check.py`.
