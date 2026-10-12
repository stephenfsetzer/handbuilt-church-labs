# Finance evals

Synthetic books test whether `finance-onboarding` and `finance-report` explain cash,
the year’s result, and the questions a treasurer needs to answer. Every church,
account, financial firm, and figure in these fixtures is invented. The evals never
connect to a church’s books and do not change skill code.

## Cases and evidence

`churches/*.py` declares the books (`CHURCH`) and expected behavior (`TRUTH`).
`books.py` generates balanced monthly balance sheets and profit-and-loss responses
in the connector’s shapes. `CHURCH.context` supplies invented facts the pastor has
already provided; the model sees those notes. `TRUTH` stays with the grader.

| Case | What makes it hard |
|---|---|
| Cedar Hollow | Year-end fund transfers, complex account numbers, frozen program funds, pass-through receipts, storm costs and a later insurance payment. |
| Millbrook | Missing online postings, clearing balances, undeposited receipts, negative liabilities, building equity with an outdated restriction label, and a misleading August reset. |
| Stonegate | One-time receipts hide an operating deficit; an anonymous brokerage account sits among banks; capitalized checking and a closed account must retain their history. |
| Harbor Light | The connector silently cuts off at 100 rows. Safe refusal is the expected outcome. |
| Lantern Hill | A July fiscal year, annual insurance, an overdraft, and a line of credit. |
| Wellspring | Seven months of books, uncategorized receipts/spending, and overstated cash coverage. |
| Redwood Crossing | Wrong monthly summaries and historical postings that change between pulls. |
| Juniper Vale | Seasonal weakness combined with missing postings, prior-year comparison, and prepaid rental revenue. |
| Alder Meadow | Partial class information, shared access, and payroll questions that require a person. |
| Maple Ridge | Profit and loss is blocked by a company-profile prompt that would require a write. |

The fixtures distinguish a booked amount from what it means. Missing income is
reason to ask about recording completeness; it does not prove that giving fell or
stayed steady. A frozen fund balance cannot establish how much is restricted or
owed. An unexplained account needs context before it becomes everyday cash.

## No-model checks

Run from the repository root with the Python returned by the runtime doctor:

```bash
python3 tools/handbuilt_runtime.py setup --format json
python3 tools/handbuilt_runtime.py doctor --format json
"<runtime.python>" evals/finance/score.py
"<runtime.python>" evals/finance/score.py millbrook --json
"<runtime.python>" -m unittest discover -s tests -p 'test_*.py'
python3 tools/pii_check.py
git diff --check
```

`score.py` runs onboarding `look`, report `setup draft`, and report `build` against
the declared truth. `monthly.py` adds stateful monthly-report scenarios, including
watch-list carry-forward, unrecorded income, revised history, rendering, status,
and final-report gates. PDFs and other run artifacts are generated in temporary
folders outside the repository.

A `gap` is a documented product weakness that is expected to fail. An unexpected
failure **or a gap that now passes** makes both text and JSON scoring commands exit
nonzero. Remove a gap note only after the corresponding fix lands. Crashes, missing
dependencies, and malformed successful responses cannot count as known gaps.
The tests also challenge the eval machinery with bad inputs and fake model
responses so an empty run cannot appear successful.

Green regression tests mean that documented behavior and gaps are stable. They do
not prove that a model is ready to ship. The monthly script checks deliberately
probe some safeguards that the skill currently assigns to the model; their gaps
identify where the scripts alone do not enforce those promises.

## Model checks

`skill_eval.py` runs the skill through Claude Code against local stand-ins. It
supports onboarding stage 1 and the monthly report workflow. Each model gets its
own run directory. The runner exposes a copy of the plugin without eval answers,
three read-only QuickBooks tools, and contained workspace operations. Live
connectors and unrestricted shell access are excluded from the run.

Run output, tool traces, generated PDFs, and grades must stay outside this public
repository. A model run needs Claude Code, `ANTHROPIC_API_KEY`, and permitted
model API access. The runner uses isolated configuration, so a host's saved login
is not used. Proxy and certificate settings are preserved.

```bash
"<runtime.python>" evals/finance/skill_eval.py all \
  --model sonnet --model opus --judge opus \
  --out ~/handbuilt-runtime/finance-evals/run-001
"<runtime.python>" evals/finance/skill_eval.py table \
  ~/handbuilt-runtime/finance-evals/run-001
```

`all` runs both skills unless restricted with `--skill`. Choose a fresh output
directory for every matrix; existing case folders are refused to prevent stale
artifacts from passing a rerun. Model aliases may be replaced with explicit IDs.
The run receipt records the requested model and resolved model IDs when the CLI
provides them. `--budget` limits each candidate invocation; judging has its own
per-call limit. `run` executes a candidate; only `grade --judge` or `all` evaluates
the model gate. See the subcommands' `--help` for individual cases.

The deterministic figure check finds amounts absent from the synthetic books; it
is a screening check, not proof that a matching number supports a particular
claim. Unmatched amounts are advisory because a transparent calculation may be
valid; passing the source-claims judge item remains mandatory. The judge evaluates
source attribution, period, account, sign, uncertainty,
required treasurer questions, prohibited conclusions, and clarity. Missing output,
failed processes, malformed or incomplete judge verdicts, and unjudged runs cannot
pass the model gate. A safe stop is graded explicitly for blocked-connector cases.

No model scores are checked into this repository. Run the model matrix for each
release candidate and report scores per case, skill, and model with its PR. A
missing credential or unavailable model is **not run**, never a passing score.

## Extending the suite

1. Invent a case and its observable context. Do not copy or paraphrase church data.
2. State what the books establish, what only a person can answer, and what must
   never be claimed. Add deterministic checks where scripts expose that behavior.
3. Register the case in `churches/__init__.py`; add generator or harness tests when
   a new fixture feature changes the evidence delivered to the model.
4. Register every new account number and every written money figure of at least
   four digits in `tools/example-accounts.txt` and `tools/example-figures.txt`.
5. Run scoring, the full unittest suite, privacy scanning, and whitespace checks.
