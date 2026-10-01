"""Render findings as a client-facing report (German, Markdown + HTML)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from jinja2 import Environment, PackageLoader, select_autoescape

from waste_finder.models import Finding
from waste_finder.registry import REGISTRY, SEVERITIES


@dataclass
class Summary:
    count: int
    monthly_eur: float  # sum of savings (D6), not of current cost
    yearly_eur: float
    unpriced: int


def summarize(findings: list[Finding]) -> Summary:
    monthly = sum(f.savings_eur or 0 for f in findings)
    return Summary(
        count=len(findings),
        monthly_eur=round(monthly, 2),
        yearly_eur=round(monthly * 12, 2),
        unpriced=sum(1 for f in findings if f.savings_eur is None),
    )


def eur(value: float | None) -> str:
    """1234.5 -> '1.234,50 €' (Austrian format)."""
    if value is None:
        return "n/a"
    return f"{value:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def render(findings: list[Finding], subscription: str, fmt: str, demo: bool = False) -> str:
    env = Environment(
        loader=PackageLoader("waste_finder", "templates"),
        autoescape=select_autoescape(enabled_extensions=("html.j2",)),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["eur"] = eur
    ordered = sorted(findings, key=lambda f: f.savings_eur or 0, reverse=True)
    return env.get_template(f"report.{fmt}.j2").render(
        findings=ordered,
        summary=summarize(findings),
        rules=REGISTRY,
        severities=SEVERITIES,
        subscription=subscription,
        today=date.today().isoformat(),
        demo=demo,
    )
