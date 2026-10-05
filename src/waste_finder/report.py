"""Render findings as a client-facing report (German, Markdown + HTML)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import partial
from typing import TYPE_CHECKING

from jinja2 import Environment, PackageLoader, select_autoescape

from waste_finder.models import Finding
from waste_finder.registry import REGISTRY, SEVERITIES

if TYPE_CHECKING:
    from waste_finder.costs import CostPeriod
    from waste_finder.trend import Trend

# German labels of the trend table rows (trend.TrendRow.status).
ROW_STATUS_DE = {"new": "neu", "resolved": "behoben", "changed": "geändert"}

# Report label for Finding.cost_source (column "Quelle" when actual costs were requested).
COST_SOURCE_LABELS = {"actual": "Ist-Kosten", "retail": "Listenpreis", None: "ohne Preis"}

# Sort key of the severity column in the HTML report (data-sort): high 3 ... info 0.
SEVERITY_RANK = {severity: rank for rank, severity in enumerate(reversed(SEVERITIES))}

# The longest bar of the HTML chart takes this share of the width; the rest is room for its value label.
CHART_MAX_PERCENT = 75.0


@dataclass
class Summary:
    count: int
    monthly_eur: float  # sum of savings (D6), not of current cost
    yearly_eur: float
    unpriced: int
    monthly_cost_eur: float = 0.0  # what the resources cost now; more than monthly_eur when some are downgrades
    ignored: int = 0  # tagged waste-finder:ignore=true or matched an exclude pattern
    below_threshold: int = 0  # saves less than min_monthly_savings
    cleanup: int = 0  # free clean-up findings, listed separately and not part of the total
    actual: int = 0  # findings priced from Cost Management (--cost-source actual); the rest are list prices


@dataclass
class Group:
    """The findings of one subscription, most expensive first."""

    subscription_id: str
    findings: list[Finding]
    monthly_eur: float


@dataclass
class ChartBar:
    """One bar of the HTML chart "Einsparpotenzial nach Problem": the savings of one rule."""

    rule: str
    label: str
    count: int  # findings of this rule
    monthly_eur: float
    percent: float  # bar length in % of the chart width


def rule_chart(findings: list[Finding]) -> list[ChartBar]:
    """Savings per rule, largest first (ties in registry order), scaled to CHART_MAX_PERCENT. Rules without savings
    are left out; with fewer than two bars there is nothing to compare, so the chart is skipped (empty list)."""
    counts: dict[str, int] = {}
    sums: dict[str, float] = {}
    for f in findings:
        counts[f.rule] = counts.get(f.rule, 0) + 1
        sums[f.rule] = sums.get(f.rule, 0.0) + (f.savings_eur or 0)
    totals = {rule: round(amount, 2) for rule, amount in sums.items()}
    order = list(REGISTRY)
    rules = sorted((r for r in totals if totals[r] > 0), key=lambda r: (-totals[r], order.index(r)))
    if len(rules) < 2:
        return []
    top = totals[rules[0]]
    return [
        ChartBar(r, REGISTRY[r].title_de, counts[r], totals[r], round(totals[r] / top * CHART_MAX_PERCENT, 2))
        for r in rules
    ]


def severity_counts(findings: list[Finding]) -> dict[str, int]:
    """Findings per severity, in report order (hoch first), only severities that occur."""
    counts = {severity: sum(1 for f in findings if f.severity == severity) for severity in SEVERITIES}
    return {severity: n for severity, n in counts.items() if n}


def summarize(findings: list[Finding], ignored: int = 0, below_threshold: int = 0, cleanup: int = 0) -> Summary:
    monthly = sum(f.savings_eur or 0 for f in findings)
    return Summary(
        count=len(findings),
        monthly_eur=round(monthly, 2),
        yearly_eur=round(monthly * 12, 2),
        unpriced=sum(1 for f in findings if f.savings_eur is None),
        monthly_cost_eur=round(sum(f.monthly_cost_eur or 0 for f in findings), 2),
        ignored=ignored,
        below_threshold=below_threshold,
        cleanup=cleanup,
        actual=sum(1 for f in findings if f.cost_source == "actual"),
    )


def cleanup_order(findings: list[Finding]) -> list[Finding]:
    """Free clean-up findings by subscription, resource group, rule and name."""
    return sorted(findings, key=lambda f: (f.subscription_id, f.resource_group.lower(), f.rule, f.name.lower()))


def by_subscription(findings: list[Finding]) -> list[Group]:
    """Group findings by subscription; the subscription with the most savings comes first."""
    groups: dict[str, list[Finding]] = {}
    for f in sorted(findings, key=lambda f: f.savings_eur or 0, reverse=True):
        groups.setdefault(f.subscription_id, []).append(f)
    result = [Group(sub, fs, summarize(fs).monthly_eur) for sub, fs in groups.items()]
    return sorted(result, key=lambda g: g.monthly_eur, reverse=True)


def currency_symbol(currency: str) -> str:
    return "€" if currency == "EUR" else currency


def eur(value: float | None, currency: str = "EUR") -> str:
    """1234.5 -> '1.234,50 €' (Austrian format); other currencies show their code: '1.234,50 CHF'."""
    if value is None:
        return "n/a"
    return f"{value:,.2f} {currency_symbol(currency)}".replace(",", "X").replace(".", ",").replace("X", ".")


def signed_eur(value: float, currency: str = "EUR") -> str:
    """Amount with its sign, for changes: '+28,91 €', '-9,97 €', '0,00 €'."""
    rounded = round(value, 2)
    sign = "+" if rounded > 0 else "-" if rounded < 0 else ""
    return sign + eur(abs(rounded), currency)


def render(
    findings: list[Finding],
    scope: str,
    fmt: str,
    demo: bool = False,
    *,
    ignored: int = 0,
    below_threshold: int = 0,
    min_savings: float = 0.0,
    currency: str = "EUR",
    cleanup: list[Finding] | None = None,
    cost_source: str = "retail",
    cost_period: CostPeriod | None = None,
    trend: Trend | None = None,
) -> str:
    env = Environment(
        loader=PackageLoader("waste_finder", "templates"),
        autoescape=select_autoescape(enabled_extensions=("html.j2",)),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["eur"] = partial(eur, currency=currency)
    env.filters["signed_eur"] = partial(signed_eur, currency=currency)
    ordered = sorted(findings, key=lambda f: f.savings_eur or 0, reverse=True)
    free = cleanup_order(cleanup or [])
    return env.get_template(f"report.{fmt}.j2").render(
        findings=ordered,
        groups=by_subscription(findings),
        cleanup=free,
        summary=summarize(findings, ignored=ignored, below_threshold=below_threshold, cleanup=len(free)),
        rules=REGISTRY,
        severities=SEVERITIES,
        scope=scope,
        min_savings=min_savings,
        currency=currency,
        currency_symbol=currency_symbol(currency),
        today=date.today().isoformat(),
        demo=demo,
        actual=cost_source == "actual",
        cost_period=cost_period.label() if cost_period else "",
        source_labels=COST_SOURCE_LABELS,
        trend=trend,
        trend_rows=trend.rows() if trend else [],
        trend_labels=ROW_STATUS_DE,
        cost_source_name=cost_source,
        chart=rule_chart(findings),
        severity_counts=severity_counts(findings),
        severity_rank=SEVERITY_RANK,
    )
