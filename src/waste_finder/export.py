"""Machine-readable output (JSON, CSV, SARIF) and the short Markdown summary for CI.

The JSON layout is described by docs/report.schema.json; bump SCHEMA_VERSION when it changes
(minor: new optional fields, major: renamed or removed fields).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

from waste_finder import __version__
from waste_finder.models import Finding
from waste_finder.registry import REGISTRY, SEVERITIES
from waste_finder.report import Summary, cleanup_order, eur, signed_eur

if TYPE_CHECKING:
    from waste_finder.costs import CostPeriod
    from waste_finder.trend import Trend

FORMATS = ("md", "html", "json", "csv", "sarif")
DEFAULT_FORMATS = ("md", "html")
SCHEMA_VERSION = "1.5"

SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
SARIF_LEVELS = {"high": "error", "medium": "warning", "low": "note", "info": "note"}
REPO_URL = "https://github.com/viache25/azure-waste-finder"

CSV_COLUMNS = (
    "subscription_id",
    "resource_group",
    "name",
    "rule",
    "title",
    "severity",
    "location",
    "sku",
    "size_gb",
    "age_days",
    "quantity",
    "monthly_cost",
    "monthly_savings",
    "currency",
    "cost_source",
    "trend",
    "resource_id",
    "command",
)


@dataclass(frozen=True)
class RunInfo:
    """What the run looked at; shared by all output formats."""

    scope: str
    currency: str = "EUR"
    demo: bool = False
    min_monthly_savings: float = 0.0
    cost_source: str = "retail"  # requested source; each finding says which one it got
    cost_period: CostPeriod | None = None  # Cost Management period when cost_source is "actual"


def _ordered(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: f.savings_eur or 0, reverse=True)


def finding_dict(f: Finding, trend: Trend | None = None) -> dict[str, Any]:
    """`trend` (from --previous) adds the finding's status and its previous savings; None leaves both null."""
    rule = REGISTRY[f.rule]
    return {
        "rule": f.rule,
        "title_de": rule.title_de,
        "title_en": rule.title_en,
        "severity": f.severity,
        "resource_id": f.resource_id,
        "subscription_id": f.subscription_id,
        "name": f.name,
        "resource_group": f.resource_group,
        "location": f.location,
        "sku": f.sku,
        "size_gb": f.size_gb,
        "os_type": f.os_type,
        "age_days": f.age_days,
        "quantity": f.quantity,
        "tags": f.tags,
        "monthly_cost": f.monthly_cost_eur,
        "monthly_savings": f.savings_eur,
        "cost_source": f.cost_source,
        "trend": trend.status(f) if trend else None,
        "previous_monthly_savings": trend.previous_amount(f) if trend else None,
        "price_note": f.price_note,
        "command": rule.remediation_command(f.resource_id),
        "docs_url": rule.docs_url,
    }


def trend_dict(trend: Trend) -> dict[str, Any]:
    return {
        "previous": {
            "generated": trend.previous.generated,
            "scope": trend.previous.scope,
            "cost_source": trend.previous.cost_source,
            "monthly_savings": trend.previous_monthly,
        },
        "monthly_savings_change": trend.monthly_change,
        "new": len(trend.new),
        "resolved": len(trend.resolved),
        "unchanged": len(trend.unchanged),
        "changed": len(trend.changed),
        "resolved_findings": [
            {
                "rule": f.rule,
                "resource_id": f.resource_id,
                "subscription_id": f.subscription_id,
                "name": f.name,
                "resource_group": f.resource_group,
                "monthly_savings": f.monthly_savings,
            }
            for f in sorted(trend.resolved, key=lambda f: f.monthly_savings or 0, reverse=True)
        ],
    }


def render_json(
    findings: list[Finding],
    summary: Summary,
    run: RunInfo,
    cleanup: list[Finding] | None = None,
    trend: Trend | None = None,
) -> str:
    data = {
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "azure-waste-finder", "version": __version__},
        "generated": date.today().isoformat(),
        "scope": run.scope,
        "demo": run.demo,
        "currency": run.currency,
        "cost_source": run.cost_source,
        "cost_period": (
            {"from": run.cost_period.start.isoformat(), "to": run.cost_period.end.isoformat()}
            if run.cost_period
            else None
        ),
        "summary": {
            "count": summary.count,
            "monthly_savings": summary.monthly_eur,
            "yearly_savings": summary.yearly_eur,
            "unpriced": summary.unpriced,
            "ignored": summary.ignored,
            "below_threshold": summary.below_threshold,
            "min_monthly_savings": run.min_monthly_savings,
            "cleanup": summary.cleanup,
            "actual_costs": summary.actual,
        },
        "findings": [finding_dict(f, trend) for f in _ordered(findings)],
        "cleanup": [finding_dict(f) for f in cleanup_order(cleanup or [])],
        "trend": trend_dict(trend) if trend else None,
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def render_csv(
    findings: list[Finding],
    summary: Summary,
    run: RunInfo,
    cleanup: list[Finding] | None = None,
    trend: Trend | None = None,
) -> str:
    """One row per finding, free clean-up findings last; amounts with a dot as decimal separator, empty if unpriced.
    `trend` is new/unchanged with --previous (empty for clean-up findings and without --previous)."""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    rows = [finding_dict(f, trend) for f in _ordered(findings)] + [
        finding_dict(f) for f in cleanup_order(cleanup or [])
    ]
    for d in rows:
        d["title"] = d["title_en"]
        d["currency"] = run.currency
        writer.writerow({k: "" if d[k] is None else d[k] for k in CSV_COLUMNS})
    return out.getvalue()


def _fingerprint(f: Finding) -> str:
    return hashlib.sha256(f"{f.rule}|{f.resource_id.lower()}".encode()).hexdigest()


def render_sarif(
    findings: list[Finding],
    summary: Summary,
    run: RunInfo,
    cleanup: list[Finding] | None = None,
    trend: Trend | None = None,
) -> str:
    """SARIF 2.1.0 for GitHub code scanning: one rule per registry entry, one result per finding (free clean-up
    findings included, as notes).

    Azure resources are not files, so each result points at the resource ID as its artifact URI
    (shown as the alert's path) and names it as a logical location. The fingerprint (rule + resource ID)
    keeps an alert stable across runs, so a resource that is cleaned up closes its alert. Code scanning tracks
    new and fixed alerts itself, so `trend` is not used here.
    """
    rule_ids = list(REGISTRY)
    rules = [
        {
            "id": r.id,
            "name": r.title_en,
            "shortDescription": {"text": r.title_en},
            "fullDescription": {"text": f"{r.title_de}. {r.why_de}"},
            "help": {"text": f"{r.action_de}\n\n{r.command}", "markdown": f"{r.action_de}\n\n`{r.command}`"},
            "helpUri": r.docs_url,
            "defaultConfiguration": {"level": SARIF_LEVELS[r.severity]},
            "properties": {"severity": r.severity, "tags": ["finops", "azure", "cost"]},
        }
        for r in REGISTRY.values()
    ]
    results = []
    for f in _ordered(findings) + cleanup_order(cleanup or []):
        rule = REGISTRY[f.rule]
        amount = eur(f.savings_eur, run.currency)
        results.append(
            {
                "ruleId": f.rule,
                "ruleIndex": rule_ids.index(f.rule),
                "level": SARIF_LEVELS[f.severity],
                "message": {"text": f"{rule.title_en}: {f.name} ({f.sku}), approx. {amount} per month"},
                "locations": [
                    {
                        "physicalLocation": {"artifactLocation": {"uri": f.resource_id.lstrip("/")}},
                        "logicalLocations": [{"fullyQualifiedName": f.resource_id, "name": f.name, "kind": "resource"}],
                    }
                ],
                "partialFingerprints": {"resourceRule/v1": _fingerprint(f)},
                "properties": {
                    "monthlyCost": f.monthly_cost_eur,
                    "monthlySavings": f.savings_eur,
                    "currency": run.currency,
                    "costSource": f.cost_source,
                    "command": rule.remediation_command(f.resource_id),
                },
            }
        )
    sarif = {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "azure-waste-finder",
                        "version": __version__,
                        "informationUri": REPO_URL,
                        "rules": rules,
                    }
                },
                "automationDetails": {"id": f"azure-waste-finder/{run.scope}/"},
                "results": results,
            }
        ],
    }
    return json.dumps(sarif, indent=2, ensure_ascii=False) + "\n"


EXPORTERS = {"json": render_json, "csv": render_csv, "sarif": render_sarif}


def render_summary(
    findings: list[Finding],
    summary: Summary,
    run: RunInfo,
    fail_over: float | None = None,
    trend: Trend | None = None,
) -> str:
    """Short German Markdown summary, meant to be appended to $GITHUB_STEP_SUMMARY."""

    def money(value: float | None) -> str:
        return eur(value, run.currency)

    lines = [
        f"### Azure Kostencheck: ca. {money(summary.monthly_eur)} pro Monat",
        "",
        f"**{summary.count}** ungenutzte Ressource(n) im Bereich `{run.scope}`, "
        f"≈ {money(summary.yearly_eur)} pro Jahr.",
    ]
    if trend:
        lines += [
            "",
            f"Seit dem letzten Bericht ({trend.previous.generated}): **{signed_eur(trend.monthly_change, run.currency)}"
            f" pro Monat**; {len(trend.new)} neu, {len(trend.resolved)} behoben, {len(trend.unchanged)} unverändert.",
        ]
    if run.cost_source == "actual":
        lines += [
            "",
            f"Kostenquelle: {summary.actual} von {summary.count} Beträgen Ist-Kosten (Azure Cost Management, "
            "amortisiert, letzte 30 Tage), die übrigen Listenpreise.",
        ]
    if fail_over is not None:
        verdict = "überschritten" if summary.monthly_eur > fail_over else "eingehalten"
        lines += ["", f"Schwelle {money(fail_over)} pro Monat: **{verdict}**."]
    if findings:
        lines += ["", "| Problem | Priorität | Anzahl | Einsparung/Monat |", "|---|---|---:|---:|"]
        per_rule: dict[str, list[Finding]] = {}
        for f in findings:
            per_rule.setdefault(f.rule, []).append(f)
        totals = {rule_id: round(sum(f.savings_eur or 0 for f in fs), 2) for rule_id, fs in per_rule.items()}
        for rule_id in sorted(per_rule, key=lambda r: totals[r], reverse=True):
            rule = REGISTRY[rule_id]
            severity = SEVERITIES[rule.severity]
            lines.append(f"| {rule.title_de} | {severity} | {len(per_rule[rule_id])} | {money(totals[rule_id])} |")
    if summary.ignored or summary.below_threshold or summary.unpriced or summary.cleanup:
        notes = [
            f"{n} {label}"
            for n, label in (
                (summary.unpriced, "ohne Preis"),
                (summary.ignored, "ignoriert"),
                (summary.below_threshold, "unter der Schwelle"),
                (summary.cleanup, "kostenlos aufzuräumen"),
            )
            if n
        ]
        lines += ["", f"Außerdem: {', '.join(notes)}."]
    return "\n".join(lines) + "\n\n"
