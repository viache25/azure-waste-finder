"""scripts/finops_issue.py: the "Azure waste report" issue of finops-check.yml (no network, gh is faked)."""

import json
import subprocess
import sys

import pytest

import finops_issue
from finops_issue import MARKER, TITLE, Action, GhIssues, decide, load_summary, main, render_body, sync_issue
from waste_finder.cli import main as finder_main


@pytest.fixture(scope="module")
def demo_report(tmp_path_factory):
    """report.json of the demo run: 15 findings, 509.03 EUR per month, trend -9.97 EUR."""
    out = tmp_path_factory.mktemp("demo")
    assert finder_main(["--demo", "--format", "json", "--out-dir", str(out)]) == 0
    return out / "report.json"


def write_report(tmp_path, monthly, findings=(), **summary):
    """A minimal schema-1.5-shaped report.json."""
    data = {
        "schema_version": "1.5",
        "generated": "2026-10-05",
        "scope": "subscription 0000",
        "currency": "EUR",
        "cost_source": "retail",
        "summary": {"count": len(findings), "monthly_savings": monthly, "yearly_savings": monthly * 12, **summary},
        "findings": list(findings),
        "cleanup": [],
    }
    path = tmp_path / "report.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def finding(name, savings, rule="unattached_disk"):
    return {
        "rule": rule,
        "title_en": "Unattached managed disk",
        "name": name,
        "resource_group": "rg",
        "monthly_savings": savings,
    }


class FakeIssues:
    def __init__(self, open_issue=None):
        self.open_issue = open_issue
        self.calls = []

    def find_open(self):
        return self.open_issue

    def create(self, body):
        self.calls.append(("create", body))
        return 42

    def update(self, number, body):
        self.calls.append(("update", number, body))

    def close(self, number, comment):
        self.calls.append(("close", number, comment))


@pytest.mark.parametrize(
    ("monthly", "count", "open_issue", "expected"),
    [
        (25.0, 3, None, Action.CREATE),  # above the threshold, no issue yet
        (25.0, 3, 7, Action.UPDATE),  # above, issue open
        (10.0, 2, None, Action.NONE),  # exactly the threshold is not above it
        (5.0, 1, None, Action.NONE),  # below: never opens a new issue
        (5.0, 1, 7, Action.UPDATE),  # below but not zero: keep the open issue current
        (0.0, 1, 7, Action.UPDATE),  # only unpriced findings left: not zero yet
        (0.0, 0, 7, Action.CLOSE),  # back to zero
        (0.0, 0, None, Action.NONE),  # zero and nothing open
    ],
)
def test_decide(monthly, count, open_issue, expected):
    assert decide(monthly, count, 10.0, open_issue) is expected


def test_threshold_zero_opens_on_any_waste():
    assert decide(0.01, 1, 0.0, None) is Action.CREATE
    assert decide(0.0, 0, 0.0, 3) is Action.CLOSE


def test_load_summary_reads_the_demo_report(demo_report):
    report = load_summary(demo_report)
    assert report.monthly == 509.03
    assert report.count == len(report.findings) == 15
    assert report.currency == "EUR"
    assert report.cleanup == 6 and report.ignored == 1
    assert report.change == -9.97 and report.previous_generated == "2026-09-04"


def test_load_summary_of_an_older_report_without_trend(tmp_path):
    report = load_summary(write_report(tmp_path, 3.36, [finding("pip-1", 3.36)]))
    assert report.change is None and report.previous_generated is None
    assert report.cost_source == "retail" and report.unpriced == 0


@pytest.mark.parametrize("content", ["not json", "{}", '{"summary": {}}', "[]"])
def test_load_summary_rejects_other_files(tmp_path, content):
    path = tmp_path / "report.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match=r"not a readable waste-finder report\.json"):
        load_summary(path)


def test_load_summary_of_a_missing_file(tmp_path):
    with pytest.raises(ValueError):
        load_summary(tmp_path / "missing.json")


def test_body_above_the_threshold(demo_report):
    body = render_body(load_summary(demo_report), 10.0, "https://github.com/o/r/actions/runs/1")
    assert body.startswith(MARKER + "\n")
    assert (
        "**About 509.03 EUR per month** (~6,108.36 EUR per year) in 15 finding(s), above the threshold of 10.00 EUR"
        in body
    )
    assert "Change since the report of 2026-09-04: **-9.97 EUR per month**" in body
    assert "- Also: 1 ignored, 6 free clean-up finding(s), not in the total" in body
    assert "artifact `finops-report` of [this run](https://github.com/o/r/actions/runs/1)" in body
    rows = [line for line in body.splitlines() if line.startswith("| ") and "EUR" in line]
    assert len(rows) == finops_issue.TOP_FINDINGS
    amounts = [float(row.split(" EUR")[0].lstrip("| ").replace(",", "")) for row in rows]
    assert amounts == sorted(amounts, reverse=True)  # largest first
    assert "... and 5 more in the full report." in body


def test_body_below_the_threshold_with_unpriced_and_growth(tmp_path):
    findings = [finding("disk-a", None), finding("disk-b", 4.5)]
    path = write_report(tmp_path, 4.5, findings, unpriced=1)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["trend"] = {"previous": {"generated": "2026-09-28"}, "monthly_savings_change": 4.5}
    path.write_text(json.dumps(data), encoding="utf-8")
    body = render_body(load_summary(path), 10.0, None)
    assert "at or below the threshold of 10.00 EUR" in body
    assert "**+4.50 EUR per month**" in body
    assert "- Also: 1 unpriced" in body
    assert "| unpriced | Unattached managed disk | `disk-a` | `rg` |" in body
    assert "more in the full report" not in body and "this run" not in body


def test_sync_creates_the_issue_above_the_threshold(demo_report):
    issues = FakeIssues()
    outcome = sync_issue(load_summary(demo_report), 100.0, issues, "https://run")
    assert (outcome.action, outcome.number) == (Action.CREATE, 42)
    assert issues.calls[0][0] == "create" and "509.03 EUR" in issues.calls[0][1]


def test_sync_updates_the_open_issue(demo_report):
    issues = FakeIssues(open_issue=7)
    outcome = sync_issue(load_summary(demo_report), 1000.0, issues)  # below the threshold, still open
    assert (outcome.action, outcome.number) == (Action.UPDATE, 7)
    assert issues.calls[0][:2] == ("update", 7) and "at or below the threshold" in issues.calls[0][2]


def test_sync_closes_at_zero(tmp_path):
    issues = FakeIssues(open_issue=7)
    outcome = sync_issue(load_summary(write_report(tmp_path, 0.0)), 10.0, issues, "https://run")
    assert (outcome.action, outcome.number) == (Action.CLOSE, 7)
    assert issues.calls == [
        ("close", 7, "No waste left in `subscription 0000` on 2026-10-05 ([run](https://run)). Closing.")
    ]


def test_sync_does_nothing_below_the_threshold_without_an_issue(tmp_path):
    issues = FakeIssues()
    outcome = sync_issue(load_summary(write_report(tmp_path, 3.0, [finding("d", 3.0)])), 10.0, issues)
    assert (outcome.action, outcome.number) == (Action.NONE, None)
    assert issues.calls == []


class FakeGh:
    """Records gh invocations and answers them like the real CLI."""

    def __init__(self, listed=()):
        self.listed = list(listed)
        self.calls = []

    def __call__(self, args, stdin=None):
        self.calls.append((list(args), stdin))
        if args[:2] == ["issue", "list"]:
            return json.dumps(self.listed)
        if args[:2] == ["issue", "create"]:
            return "https://github.com/o/r/issues/12\n"
        return ""


def test_gh_find_open_needs_title_and_marker():
    gh = FakeGh(
        [
            {"number": 3, "title": "Azure waste report", "body": "opened by hand"},
            {"number": 9, "title": "Azure waste report (old)", "body": MARKER},
            {"number": 8, "title": TITLE, "body": f"{MARKER}\nnewer"},
            {"number": 5, "title": TITLE, "body": f"{MARKER}\nolder"},
            {"number": 6, "title": TITLE, "body": None},
        ]
    )
    assert GhIssues("o/r", gh).find_open() == 5  # the oldest bot issue
    args, _ = gh.calls[0]
    assert args[:2] == ["issue", "list"] and "--repo" in args and "o/r" in args and "open" in args


def test_gh_find_open_without_a_match():
    assert GhIssues("o/r", FakeGh([{"number": 1, "title": "bug", "body": ""}])).find_open() is None


def test_gh_create_update_close_commands():
    gh = FakeGh()
    issues = GhIssues("o/r", gh)
    assert issues.create("body text") == 12
    issues.update(12, "new body")
    issues.close(12, "done")
    assert gh.calls == [
        (["issue", "create", "--repo", "o/r", "--title", TITLE, "--body-file", "-"], "body text"),
        (["issue", "edit", "12", "--repo", "o/r", "--body-file", "-"], "new body"),
        (["issue", "close", "12", "--repo", "o/r", "--comment", "done"], None),
    ]


def test_run_gh_returns_stdout(monkeypatch):
    def fake_run(cmd, **kwargs):
        assert cmd[0] == "gh" and kwargs["input"] == "in"
        return subprocess.CompletedProcess(cmd, 0, stdout="out", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert finops_issue.run_gh(["issue", "list"], "in") == "out"


def test_run_gh_raises_with_stderr(monkeypatch, capsys):
    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="HTTP 403\n")
    )
    with pytest.raises(subprocess.CalledProcessError):
        finops_issue.run_gh(["issue", "create"])
    assert "HTTP 403" in capsys.readouterr().err


def test_main_syncs_and_prints(demo_report, capsys):
    issues = FakeIssues(open_issue=4)
    code = main(["--report", str(demo_report), "--threshold", "20", "--repo", "o/r"], issues=issues)
    assert code == 0
    assert capsys.readouterr().out == "Azure waste report: update #4 (509.03 EUR per month, threshold 20.00 EUR)\n"
    assert issues.calls[0][:2] == ("update", 4)


def test_main_dry_run_does_not_call_gh(demo_report, capsys, monkeypatch):
    monkeypatch.setattr(finops_issue, "run_gh", lambda *a: pytest.fail("gh must not run"))
    assert main(["--report", str(demo_report), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("without an open issue: create\n") and MARKER in out


def test_main_uses_gh_for_the_repository(demo_report, monkeypatch, capsys):
    gh = FakeGh()
    monkeypatch.setattr(finops_issue, "run_gh", gh)
    assert main(["--report", str(demo_report), "--repo", "o/r"]) == 0
    assert [c[0][:2] for c in gh.calls] == [["issue", "list"], ["issue", "create"]]
    assert "create #12" in capsys.readouterr().out


def test_main_needs_a_repository(demo_report, capsys):
    assert main(["--report", str(demo_report)]) == 2
    assert "--repo is required" in capsys.readouterr().err


def test_main_rejects_a_bad_report(tmp_path, capsys):
    assert main(["--report", str(tmp_path / "missing.json"), "--dry-run"]) == 2
    assert "not a readable waste-finder report.json" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["ten", "-1", "nan"])
def test_main_rejects_a_bad_threshold(demo_report, value):
    with pytest.raises(SystemExit) as exit_info:
        main(["--report", str(demo_report), "--threshold", value, "--dry-run"])
    assert exit_info.value.code == 2


def test_script_runs_as_a_program(demo_report, monkeypatch, capsys):
    import runpy

    monkeypatch.setattr(sys, "argv", ["finops_issue.py", "--report", str(demo_report), "--dry-run"])
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(finops_issue.__file__, run_name="__main__")
    assert exit_info.value.code == 0
    assert "without an open issue: create" in capsys.readouterr().out
