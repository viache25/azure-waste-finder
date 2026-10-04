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
    )
