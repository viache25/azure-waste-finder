#!/usr/bin/env python3
"""Keep one GitHub issue "Azure waste report" in line with a waste-finder report.json.

Used by .github/workflows/finops-check.yml after the weekly scan:

    python scripts/finops_issue.py --report reports/report.json --threshold 10 \
        --repo viache25/azure-waste-finder --run-url https://github.com/.../actions/runs/123

Decision (see ``decide``), with "zero" meaning no finding left outside the free clean-up section:

    monthly waste > threshold   -> open the issue, or update the open one
    zero                        -> close the open issue with a comment
    anything in between         -> update the open issue, never open a new one

The issue is found by its exact title plus a hidden marker in the body, so an issue someone else opens
with the same title is left alone. GitHub is reached through the ``gh`` CLI (``GH_TOKEN`` in Actions);
``--dry-run`` prints the decision and the body without calling it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

TITLE = "Azure waste report"
MARKER = "<!-- azure-waste-finder:finops-check -->"
ARTIFACT = "finops-report"  # name of the report artifact in finops-check.yml
TOP_FINDINGS = 10

EXIT_OK = 0
EXIT_USAGE = 2


class Action(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    CLOSE = "close"
    NONE = "none"


def decide(monthly: float, count: int, threshold: float, open_issue: int | None) -> Action:
    """What to do with the issue for a run with ``count`` findings worth ``monthly`` per month."""
    if monthly > threshold:
        return Action.UPDATE if open_issue else Action.CREATE
    if count == 0 and monthly <= 0:
        return Action.CLOSE if open_issue else Action.NONE
    return Action.UPDATE if open_issue else Action.NONE


@dataclass(frozen=True)
class Finding:
    rule: str
    title: str
    name: str
    resource_group: str
    monthly_savings: float | None


@dataclass(frozen=True)
class ReportSummary:
    generated: str
    scope: str
    currency: str
    cost_source: str
    monthly: float
    yearly: float
    count: int
    unpriced: int
    ignored: int
    cleanup: int
    change: float | None
    previous_generated: str | None
    findings: tuple[Finding, ...]


def load_summary(path: Path) -> ReportSummary:
    """Read what the issue needs from report.json (any 1.x schema); ValueError if it is not a report."""
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        summary = data["summary"]
        trend = data.get("trend") or {}
        findings = tuple(
            Finding(
                rule=str(f["rule"]),
                title=str(f.get("title_en") or f["rule"]),
                name=str(f["name"]),
                resource_group=str(f.get("resource_group") or ""),
                monthly_savings=None if f.get("monthly_savings") is None else float(f["monthly_savings"]),
            )
            for f in data["findings"]
        )
        return ReportSummary(
            generated=str(data["generated"]),
            scope=str(data["scope"]),
            currency=str(data["currency"]),
            cost_source=str(data.get("cost_source") or "retail"),
            monthly=float(summary["monthly_savings"]),
            yearly=float(summary["yearly_savings"]),
            count=int(summary["count"]),
            unpriced=int(summary.get("unpriced", 0)),
            ignored=int(summary.get("ignored", 0)),
            cleanup=int(summary.get("cleanup", 0)),
            change=None if trend.get("monthly_savings_change") is None else float(trend["monthly_savings_change"]),
            previous_generated=(trend.get("previous") or {}).get("generated"),
            findings=findings,
        )
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise ValueError(f"{path} is not a readable waste-finder report.json: {e}") from e


def money(amount: float | None, currency: str) -> str:
    return "unpriced" if amount is None else f"{amount:,.2f} {currency}"


def render_body(report: ReportSummary, threshold: float, run_url: str | None) -> str:
    """Issue body: totals, trend, the largest findings and where the full report is."""
    above = report.monthly > threshold
    verdict = "above" if above else "at or below"
    lines = [
        MARKER,
        f"**About {money(report.monthly, report.currency)} per month** "
        f"(~{money(report.yearly, report.currency)} per year) in {report.count} finding(s), "
        f"{verdict} the threshold of {money(threshold, report.currency)}.",
        "",
        f"- Scope: `{report.scope}`, scanned {report.generated}, cost source `{report.cost_source}`",
    ]
    if report.change is not None:
        sign = "+" if report.change > 0 else ""
        lines.append(
            f"- Change since the report of {report.previous_generated}: "
            f"**{sign}{money(report.change, report.currency)} per month**"
        )
    extra = [
        f"{report.unpriced} unpriced" if report.unpriced else "",
        f"{report.ignored} ignored" if report.ignored else "",
        f"{report.cleanup} free clean-up finding(s), not in the total" if report.cleanup else "",
    ]
    if any(extra):
        lines.append("- Also: " + ", ".join(e for e in extra if e))
    if report.findings:
        ranked = sorted(report.findings, key=lambda f: f.monthly_savings or 0, reverse=True)
        lines += ["", "| Savings per month | Rule | Resource | Resource group |", "|---:|---|---|---|"]
        lines += [
            f"| {money(f.monthly_savings, report.currency)} | {f.title} | `{f.name}` | `{f.resource_group}` |"
            for f in ranked[:TOP_FINDINGS]
        ]
        if len(ranked) > TOP_FINDINGS:
            lines.append(f"\n... and {len(ranked) - TOP_FINDINGS} more in the full report.")
    lines.append("")
    if run_url:
        lines.append(
            f"Full German report (Markdown, HTML, JSON with the `az` command per finding): artifact `{ARTIFACT}` "
            f"of [this run]({run_url})."
        )
    lines.append(
        "_Kept up to date by `finops-check.yml`: updated on every run while open, closed automatically when no "
        "waste is left. The tool is read-only; acting on a finding is up to you._"
    )
    return "\n".join(lines) + "\n"


def render_close_comment(report: ReportSummary, run_url: str | None) -> str:
    where = f" ([run]({run_url}))" if run_url else ""
    return f"No waste left in `{report.scope}` on {report.generated}{where}. Closing."


class Issues(Protocol):
    def find_open(self) -> int | None: ...
    def create(self, body: str) -> int: ...
    def update(self, number: int, body: str) -> None: ...
    def close(self, number: int, comment: str) -> None: ...


Runner = Callable[[Sequence[str], str | None], str]


def run_gh(args: Sequence[str], stdin: str | None = None) -> str:
    """Run gh, return stdout; raises CalledProcessError (with gh's stderr) on failure."""
    result = subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr, end="")
        raise subprocess.CalledProcessError(result.returncode, ["gh", *args], result.stdout, result.stderr)
    return result.stdout


class GhIssues:
    """The issue in one repository, through the gh CLI."""

    def __init__(self, repo: str, run: Runner | None = None) -> None:
        self.repo = repo
        self.run: Runner = run or run_gh

    def find_open(self) -> int | None:
        out = self.run(
            ["issue", "list", "--repo", self.repo, "--state", "open", "--limit", "500", "--json", "number,title,body"],
            None,
        )
        numbers = [i["number"] for i in json.loads(out) if i["title"] == TITLE and MARKER in (i.get("body") or "")]
        return min(numbers) if numbers else None

    def create(self, body: str) -> int:
        url = self.run(["issue", "create", "--repo", self.repo, "--title", TITLE, "--body-file", "-"], body)
        return int(url.strip().rstrip("/").rsplit("/", 1)[-1])

    def update(self, number: int, body: str) -> None:
        self.run(["issue", "edit", str(number), "--repo", self.repo, "--body-file", "-"], body)

    def close(self, number: int, comment: str) -> None:
        self.run(["issue", "close", str(number), "--repo", self.repo, "--comment", comment], None)


@dataclass(frozen=True)
class Outcome:
    action: Action
    number: int | None


def sync_issue(report: ReportSummary, threshold: float, issues: Issues, run_url: str | None = None) -> Outcome:
    """Apply ``decide`` to GitHub: create, update or close the issue, or leave everything as it is."""
    number = issues.find_open()
    action = decide(report.monthly, report.count, threshold, number)
    if action is Action.CREATE:
        number = issues.create(render_body(report, threshold, run_url))
    elif action is Action.UPDATE and number is not None:
        issues.update(number, render_body(report, threshold, run_url))
    elif action is Action.CLOSE and number is not None:
        issues.close(number, render_close_comment(report, run_url))
    return Outcome(action, number)


def parse_threshold(value: str) -> float:
    try:
        threshold = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {value!r}") from None
    if threshold < 0 or threshold != threshold:  # NaN
        raise argparse.ArgumentTypeError(f"must be a number >= 0: {value!r}")
    return threshold


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    p.add_argument("--report", type=Path, required=True, help="report.json of this run")
    p.add_argument("--threshold", type=parse_threshold, default=10.0, help="Monthly amount that opens the issue")
    p.add_argument("--repo", help="owner/name, e.g. $GITHUB_REPOSITORY (required unless --dry-run)")
    p.add_argument("--run-url", help="Link to the workflow run with the report artifact")
    p.add_argument("--dry-run", action="store_true", help="Print the decision and body; do not call gh")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None, issues: Issues | None = None) -> int:
    args = parse_args(argv)
    try:
        report = load_summary(args.report)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USAGE
    if args.dry_run:
        action = decide(report.monthly, report.count, args.threshold, None)
        print(f"without an open issue: {action}")
        print(render_body(report, args.threshold, args.run_url))
        return EXIT_OK
    if issues is None:
        if not args.repo:
            print("error: --repo is required unless --dry-run", file=sys.stderr)
            return EXIT_USAGE
        issues = GhIssues(args.repo)
    outcome = sync_issue(report, args.threshold, issues, args.run_url)
    target = f" #{outcome.number}" if outcome.number is not None else ""
    print(
        f"{TITLE}: {outcome.action}{target} "
        f"({money(report.monthly, report.currency)} per month, threshold {money(args.threshold, report.currency)})"
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
