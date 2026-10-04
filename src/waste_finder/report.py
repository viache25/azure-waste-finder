"""Render findings as a client-facing report (German, Markdown + HTML)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import partial

from jinja2 import Environment, PackageLoader, select_autoescape

from waste_finder.models import Finding
from waste_finder.registry import REGISTRY, SEVERITIES


@dataclass
class Summary:
    count: int
    monthly_eur: float  # sum of savings (D6), not of current cost
    yearly_eur: float
    unpriced: int
    monthly_cost_eur: float = 0.0  # what the resources cost now; more than monthly_eur when some are downgrades
    ignored: int = 0  # tagged waste-finder:ignore=true or matched an exclude pattern
    below_threshold: int = 0  # saves less than min_monthly_savings


@dataclass
class Group:
    """The findings of one subscription, most expensive first."""

    subscription_id: str
    findings: list[Finding]
    monthly_eur: float


def summarize(findings: list[Finding], ignored: int = 0, below_threshold: int = 0) -> Summary:
    monthly = sum(f.savings_eur or 0 for f in findings)
    return Summary(
        count=len(findings),
        monthly_eur=round(monthly, 2),
        yearly_eur=round(monthly * 12, 2),
        unpriced=sum(1 for f in findings if f.savings_eur is None),
        monthly_cost_eur=round(sum(f.monthly_cost_eur or 0 for f in findings), 2),
        ignored=ignored,
        below_threshold=below_threshold,
    )


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
) -> str:
    env = Environment(
        loader=PackageLoader("waste_finder", "templates"),
        autoescape=select_autoescape(enabled_extensions=("html.j2",)),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["eur"] = partial(eur, currency=currency)
    ordered = sorted(findings, key=lambda f: f.savings_eur or 0, reverse=True)
    return env.get_template(f"report.{fmt}.j2").render(
        findings=ordered,
        groups=by_subscription(findings),
        summary=summarize(findings, ignored=ignored, below_threshold=below_threshold),
        rules=REGISTRY,
        severities=SEVERITIES,
        scope=scope,
        min_savings=min_savings,
        currency=currency,
        currency_symbol=currency_symbol(currency),
        today=date.today().isoformat(),
        demo=demo,
    )
