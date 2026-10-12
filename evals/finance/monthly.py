"""Stateful monthly report evals against synthetic books, with real PDF rendering.

The truth here describes actions over successive editions, not renderer internals. Outputs
live in a temporary church folder. Review and final-file protection are skill promises;
the explicit gaps below record where the scripts cannot yet enforce those promises.
"""
from __future__ import annotations

import calendar
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

import books as B
from churches import ALL

# These scenarios are controlled variations of the invented case books.
# Changing a source means regenerating both reports from the ledger, never editing a
# reported answer to manufacture the expected difference.
TRUTH = {
    "redwood_crossing": {
        "history_adjustment": 1250,
        "checks": [
            {"id": "monthly_readiness", "why": "A missing saved pull blocks readiness; complete sources permit a draft."},
            {"id": "monthly_totals", "why": "The month and year describe the ledger and exclude the prior-month pull from this month's income."},
            {"id": "monthly_watch", "why": "Measured items update; unresolved facts need a person; resolved items leave the list."},
            {"id": "monthly_render", "why": "The saved draft PDF and receipt must agree, fit the board packet, and carry the review marker."},
            {"id": "monthly_history", "why": "A real earlier posting changes fresh pulls and must be flagged without rewriting the previous edition."},
            {"id": "monthly_approval", "why": "The treasurer has not approved the short answer or confirmed obligations.",
             "gap": "The skill requires treasurer review, but setting status to final bypasses it in the renderer."},
            {"id": "monthly_final_build_immutable", "why": "A rebuild must leave the approved report, PDF, and receipt unchanged.",
             "gap": "The skill requires final editions to stay unchanged; build overwrites a final report.json."},
            {"id": "monthly_final_render_immutable", "why": "A modified report cannot silently replace an already finalized PDF and receipt.",
             "gap": "The skill requires final editions to stay unchanged; render overwrites an existing final PDF and receipt."},
        ],
    },
    "juniper_vale": {
        "pending_amount": 1250,
        "pending_label": "Juniper room hire paid August 21; not yet recorded",
        "checks": [
            {"id": "monthly_pending_income", "why": "Known money received stays separate from recorded income, retaining its source facts and a visible caveat."},
            {"id": "monthly_unposted_income", "why": "No posted income is an incomplete month; the draft and PDF must read the year through the prior month."},
        ],
    },
}


def previous_month(month):
    year, mon = B.parse(month)
    return B.key(year if mon > 1 else year - 1, mon - 1 if mon > 1 else 12)


def revised_books(church, amount):
    """An invented expense was posted to the month before the previous edition."""
    changed = deepcopy(church)
    changed["opening_retained"] = B.Books(church).opening_retained
    changed.pop("cash_end", None)
    earlier = previous_month(previous_month(church["last_month"]))
    account = next(a for a in changed["pl"] if a["section"] not in B.INCOME_SIDE and a.get("base", 0) > 0)
    account.setdefault("posts", {})[earlier] = account.get("posts", {}).get(earlier, 0) + amount
    return B.Books(changed)


def unposted_books(church):
    """The current month's income has not yet been posted; prior books are intact."""
    changed = deepcopy(church)
    changed["opening_retained"] = B.Books(church).opening_retained
    changed.pop("cash_end", None)
    for account in changed["pl"]:
        if account["section"] in B.INCOME_SIDE:
            account["to"] = min(account.get("to", church["last_month"]), previous_month(church["last_month"]))
    return B.Books(changed)


def ledger_truth(books, month):
    year, mon = B.parse(month)
    amounts = [(a["section"], books.amount(a, year, mon)) for a in books.pl_accounts]
    return {"income": round(sum(value for section, value in amounts if section in B.INCOME_SIDE)),
            "spending": round(sum(value for section, value in amounts if section not in B.INCOME_SIDE)),
            "result": round(books.period_result((year, 1), (year, mon)))}


def pdf_contains(words, text):
    """PDF extraction inserts spaces in letter-spaced headings."""
    return re.sub(r"\s+", "", text).casefold() in re.sub(r"\s+", "", words).casefold()


class MonthlyRun:
    def __init__(self, module, root):
        # Imported lazily: score imports this module to append monthly results.
        import score
        self.call, self.script = score.call, score.REPORT
        self.module, self.root = module, root
        self.books = B.Books(module.CHURCH)
        self.month = module.CHURCH["last_month"]
        self.before = previous_month(self.month)
        self.board = root / "finance/board"
        self.initial = score.Run(module, root)
        self.require(self.initial.draft_code == 0, self.initial.draft_err)
        for arguments in (("setup", "budget", "--year", self.month[:4], "--none"),
                          ("setup", "one-time", "--none"),
                          ("setup", "apply", "--approved-by", "Pat Example")):
            out, code, err = self.command(*arguments)
            self.require(code == 0, err)
        self.config_path = self.board / "config.json"
        config = self.read(self.config_path)
        expense = next(a for a in self.books.pl_accounts if a["section"] not in B.INCOME_SIDE and a.get("base", 0) > 0)
        self.metric_account = expense["name"]
        # This is a cumulative cost under observation, so additional positive spending is
        # explicitly worse. It is not a claim that cumulative spending is over budget.
        config["metrics"] = {"observed_cost": {"accounts": [expense["name"].split()[0]]}}
        config["watch_seed"] = []
        self.write(self.config_path, config)
        self.write(root / "finance/onboarding-state.json", {"locked": True, "readiness": []})

    @staticmethod
    def require(ok, message):
        if not ok:
            raise RuntimeError(message[-700:])

    @staticmethod
    def read(path):
        return json.loads(path.read_text())

    @staticmethod
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def command(self, *arguments):
        return self.call(self.script, self.root, *arguments)

    def path(self, month=None):
        return self.board / (month or self.month) / "report.json"

    def pulls(self, month, books=None):
        books = books or self.books
        year, mon = B.parse(month)
        folder = self.board / month / "pulls"
        paths = {}
        for name, data in (("balance-sheet", books.balance_sheet((year, mon))),
                           ("pl-ytd", books.pl((year, 1), (year, mon)))):
            paths[name] = folder / (name + ".json")
            self.write(paths[name], data)
        if mon > 1:
            paths["pl-prior"] = folder / "pl-prior.json"
            self.write(paths["pl-prior"], books.pl((year, 1), (year, mon - 1)))
        return paths

    def build(self, month=None, books=None, extra=()):
        month = month or self.month
        paths = self.pulls(month, books)
        arguments = ["build", "--month", month, "--prepared", "2026-09-10"]
        for name, path in paths.items():
            arguments += ["--" + name, str(path)]
        out, code, err = self.command(*arguments, *extra)
        self.require(code == 0, "build: " + err)
        return self.read(self.path(month)), out

    def render(self, month=None):
        out, code, err = self.command("render", str(self.path(month)))
        self.require(code == 0, "render: " + err)
        pdf = Path(out["pdf"])
        # Extract the delivered PDF, not only the HTML that was intended to render.
        done = subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True, timeout=30)
        self.require(done.returncode == 0, "PDF text extraction: " + done.stderr)
        words = " ".join(done.stdout.split())
        return out, words, self.read(Path(out["receipt"]))

    def snapshot(self):
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.path().parent.iterdir() if p.is_file() and p.suffix in (".pdf", ".json")}


def _standard(run, truth):
    observed = {}
    run.build(run.before)
    old = run.read(run.path(run.before))
    old["watch"] = [
        {"id": "cost", "title": "Cost under observation", "metric_key": "observed_cost",
         "metric": old["metrics"]["observed_cost"], "better": "down", "status": "New",
         "latest": "Observed through July.", "next": "Council to review the next statement.",
         "latest_template": "{observed_cost} spent through {month_name}."},
        {"id": "manual", "title": "Room hire agreement", "status": "New",
         "latest": "Waiting for the signed agreement.", "next": "Treasurer to ask about the signature."},
        {"id": "done", "title": "Insurance renewal", "status": "Resolved",
         "latest": "Renewal received.", "next": "No next step."},
    ]
    run.write(run.path(run.before), old)
    prior_bytes = run.path(run.before).read_bytes()
    missing, _, _ = run.command("status", "--month", run.month)
    report, out = run.build()
    ready, _, _ = run.command("status", "--month", run.month)
    observed["monthly_readiness"] = (missing.get("status") == "blocked" and ready.get("status") == "ready",
                                       f"without current pulls: {missing.get('status')}; after pulls: {ready.get('status')}")
    expected = ledger_truth(run.books, run.month)
    got = {"income": report["this_month"]["came_in"], "spending": report["this_month"]["went_out"],
           "result": report["plan"]["actual"]}
    observed["monthly_totals"] = (got == expected and not report.get("history_change"), f"reported {got}; ledger {expected}; unchanged history flagged={bool(report.get('history_change'))}")
    watches = {item["id"]: item for item in report["watch"]}
    measured = watches.get("cost", {})
    manual = watches.get("manual", {})
    year, mon = B.parse(run.month)
    source_metric = round(run.books.period_totals((year, 1), (year, mon))[run.metric_account])
    watch_ok = (set(watches) == {"cost", "manual"} and measured.get("metric") == source_metric
                and measured.get("status") == "Worse" and calendar.month_name[mon] in measured.get("latest", "")
                and manual.get("needs_update") is True and manual.get("next") == old["watch"][1]["next"]
                and manual.get("title") in out.get("needs_a_person", []))
    observed["monthly_watch"] = (watch_ok, f"watch IDs={sorted(watches)}, measured={measured.get('status')}, metric={measured.get('metric')} (ledger {source_metric}), manual review={manual.get('title') in out.get('needs_a_person', [])}")
    rendered, words, receipt = run.render()
    render_ok = (rendered.get("status") == "ready_for_review" and rendered.get("checks", {}).get("pages") in (1, 2)
                 and receipt.get("status") == "draft" and receipt.get("checks", {}).get("figures_verified") is True
                 and pdf_contains(words, "Draft for review") and pdf_contains(words, run.module.CHURCH["governing_body"])
                 and "Cost under observation" in words and "Worse" in words)
    observed["monthly_render"] = (render_ok, f"pages={rendered.get('checks', {}).get('pages')}, receipt={receipt.get('status')}, figures={receipt.get('checks', {}).get('figures_verified')}, draft marker={pdf_contains(words, 'Draft for review')}")

    changed = revised_books(run.module.CHURCH, truth["history_adjustment"])
    changed_report, changed_out = run.build(books=changed)
    _, changed_words, _ = run.render()
    history = changed_report.get("history_change") or {}
    prior_truth = ledger_truth(changed, run.before)["result"]
    history_ok = (history.get("was") == old["plan"]["actual"] and history.get("now") == prior_truth
                  and any("changed since last month" in line for line in changed_out.get("needs_a_person", []))
                  and "Earlier months changed" in changed_words and run.path(run.before).read_bytes() == prior_bytes)
    observed["monthly_history"] = (history_ok, f"saved prior={old['plan']['actual']}; revised ledger={prior_truth}; flagged before/after={history.get('was')}/{history.get('now')}; prior file preserved={run.path(run.before).read_bytes() == prior_bytes}")

    # Test the attempted bypass with real unresolved human review state.
    report, _ = run.build()
    report["meta"]["status"] = "final"
    run.write(run.path(), report)
    bypass, code, err = run.command("render", str(run.path()))
    run.require(code == 0 or bool(re.search(r"approv|obligation|confirm|review", err, re.I)),
                "Final review attempt failed for an unrelated reason: " + err)
    observed["monthly_approval"] = (code != 0 and bool(re.search(r"approv|obligation|confirm|review", err, re.I)),
                                     f"render exit={code}, status={bypass.get('status')}; short answer={report['short_answer_status']}; obligations={sorted({o['status'] for o in report['obligations']})}")

    # Supply all currently expressible review fields to establish a final edition.
    report["short_answer_status"] = "approved by Pat Example"
    for obligation in report["obligations"]:
        obligation["status"] = "Current: confirmed by Pat Example"
    for item in report["watch"]:
        item.pop("needs_update", None)
    run.write(run.path(), report)
    run.render()
    saved_report = run.path().read_bytes()
    saved = run.snapshot()
    paths = run.pulls(run.month)
    _, build_code, build_err = run.command("build", "--month", run.month, "--prepared", "2026-09-11",
        "--balance-sheet", str(paths["balance-sheet"]), "--pl-ytd", str(paths["pl-ytd"]), "--pl-prior", str(paths["pl-prior"]))
    observed["monthly_final_build_immutable"] = (run.snapshot() == saved,
        f"rebuild exit={build_code}; final artifacts unchanged={run.snapshot() == saved}; {build_err.strip()[-100:] if build_code else ''}")
    # Restore the final source before independently testing renderer replacement.
    run.path().write_bytes(saved_report)
    report["short_answer"] += " The council will discuss the room hire agreement."
    run.write(run.path(), report)
    before_render = run.snapshot()
    _, render_code, render_err = run.command("render", str(run.path()))
    after_render = run.snapshot()
    protected = all(after_render.get(name) == digest for name, digest in before_render.items() if name != "report.json")
    observed["monthly_final_render_immutable"] = (protected,
        f"rerender exit={render_code}; final PDF and receipt unchanged={protected}; {render_err.strip()[-100:] if render_code else ''}")
    return observed


def _income(run, truth):
    observed = {}
    recorded = ledger_truth(run.books, run.month)
    report, _ = run.build(extra=("--unrecorded", f"{truth['pending_amount']}|{truth['pending_label']}"))
    _, words, _ = run.render()
    pending = report["plan"]["unrecorded"]
    ready = {item["id"]: item for item in report.get("readiness") or []}
    pending_ok = (pending == [{"amount": truth["pending_amount"], "label": truth["pending_label"]}]
                  and report["plan"]["actual"] == recorded["result"] and report["this_month"]["came_in"] == recorded["income"]
                  and "unrecorded_income" in ready and f"${truth['pending_amount']:,}" in words
                  and "not yet recorded" in words)
    observed["monthly_pending_income"] = (pending_ok,
        f"pending={pending}; recorded result={report['plan']['actual']} (ledger {recorded['result']}); PDF caveat={'not yet recorded' in words}")
    books = unposted_books(run.module.CHURCH)
    report, output = run.build(books=books)
    _, words, _ = run.render()
    year, mon = B.parse(run.month)
    previous_name, month_name = calendar.month_name[mon - 1], calendar.month_name[mon]
    prior = ledger_truth(books, run.before)["result"]
    prior_text = f"${abs(prior):,} {'ahead' if prior >= 0 else 'short'}"
    unposted_ok = (report["this_month"]["came_in"] == 0 and report["this_month"].get("unrecorded") is True
                   and f"read the year through {previous_name}" in report["short_answer"]
                   and prior_text in report["short_answer"] and f"{month_name} not yet recorded" in words
                   and f"Through {previous_name}; {month_name} not yet recorded" in words
                   and any("looks unrecorded" in line for line in output.get("needs_a_person", [])))
    observed["monthly_unposted_income"] = (unposted_ok,
        f"income={report['this_month']['came_in']}; prior ledger result={prior}; caveat in PDF={f'{month_name} not yet recorded' in words}; short answer={report['short_answer']!r}")
    return observed


def score_monthly(cid):
    """Return score.py's result schema; cases without a monthly scenario have no checks."""
    module = ALL[cid]
    truth = TRUTH.get(cid)
    if truth is None:
        return {"church": cid, "name": module.CHURCH["name"], "truth": {}, "results": []}
    with tempfile.TemporaryDirectory(prefix="finance-monthly-eval-") as tmp:
        try:
            run = MonthlyRun(module, Path(tmp) / cid)
            observed = _standard(run, truth) if "history_adjustment" in truth else _income(run, truth)
        except (RuntimeError, KeyError, ValueError, OSError, subprocess.TimeoutExpired) as error:
            # A missing runtime, failed setup, or malformed artifact is an infrastructure
            # failure, never evidence that a known workflow gap still exists.
            return {"church": cid, "name": module.CHURCH["name"], "truth": truth,
                    "results": [{"church": cid, "check": "monthly_scenario_completed", "passed": False,
                                 "gap": None, "why": "All scenario operations must complete before checking known weaknesses.",
                                 "seen": f"{type(error).__name__}: {error}"}]}
    results = [{"church": cid, "check": spec["id"], "passed": bool(observed[spec["id"]][0]),
                "gap": spec.get("gap"), "why": spec["why"], "seen": observed[spec["id"]][1]}
               for spec in truth["checks"]]
    return {"church": cid, "name": module.CHURCH["name"], "truth": truth, "results": results}
