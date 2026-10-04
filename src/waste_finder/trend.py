"""Trend between runs (`--previous <report.json>`): new, resolved and unchanged findings, change in €/month.

A finding is the same in both runs when rule and resource ID (case-insensitive) match. Only findings of the
rules that ran this time are compared, so `--rules` does not make the other rules look resolved. Free clean-up
findings are not compared; they are not part of the total either.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, NamedTuple

from waste_finder.config import ConfigError
from waste_finder.models import Finding

TrendStatus = Literal["new", "unchanged"]


@dataclass(frozen=True)
class PreviousFinding:
    rule: str
    resource_id: str
    name: str
    resource_group: str
    subscription_id: str
    monthly_savings: float | None

    @property
    def key(self) -> tuple[str, str]:
        return self.rule, self.resource_id.lower()


@dataclass(frozen=True)
class PreviousReport:
    generated: str
    scope: str
    currency: str
    cost_source: str  # "retail" for reports older than schema 1.4
    findings: tuple[PreviousFinding, ...]


class TrendRow(NamedTuple):
    """One line of the report's trend table."""

    status: str  # new | resolved | changed
    name: str
    rule: str
    subscription_id: str
    previous: float | None  # monthly savings in the previous run; None for new findings
    current: float | None  # monthly savings now; None for resolved findings


def _key(f: Finding) -> tuple[str, str]:
    return f.rule, f.resource_id.lower()


def _amount(value: Any, path: Path | str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigError(f"--previous {path}: amounts must be numbers, got {value!r}")
    return float(value)


def load_previous(path: Path) -> PreviousReport:
    """Read a report.json written by `--format json` (any 1.x schema version)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError(f"cannot read --previous {path}: {e}") from e
    return parse_previous(text, path)


def parse_previous(text: str, path: Path | str) -> PreviousReport:
    """`path` is only used in error messages."""
    try:
        data = json.loads(text)
    except ValueError as e:
        raise ConfigError(f"cannot read --previous {path}: {e}") from e
    tool = data.get("tool") if isinstance(data, dict) else None
    if not isinstance(tool, dict) or tool.get("name") != "azure-waste-finder":
        raise ConfigError(f"--previous {path} is not a report.json of azure-waste-finder")
    version = str(data.get("schema_version", ""))
    if not version.startswith("1."):
        raise ConfigError(f"--previous {path}: unsupported schema_version {version!r} (expected 1.x)")
    try:
        findings = tuple(
            PreviousFinding(
                rule=str(f["rule"]),
                resource_id=str(f["resource_id"]),
                name=str(f["name"]),
                resource_group=str(f.get("resource_group", "")),
                subscription_id=str(f.get("subscription_id", "")),
                monthly_savings=_amount(f.get("monthly_savings"), path),
            )
            for f in data["findings"]
        )
        return PreviousReport(
            generated=str(data["generated"]),
            scope=str(data["scope"]),
            currency=str(data["currency"]),
            cost_source=str(data.get("cost_source", "retail")),
            findings=findings,
        )
    except (KeyError, TypeError) as e:
        raise ConfigError(f"--previous {path}: missing or invalid field {e}") from e


@dataclass(frozen=True)
class Trend:
    previous: PreviousReport
    new: tuple[Finding, ...]
    resolved: tuple[PreviousFinding, ...]
    unchanged: tuple[Finding, ...]
    previous_savings: dict[tuple[str, str], float | None]  # key -> previous monthly savings, for unchanged

    @property
    def previous_monthly(self) -> float:
        """Previous total over the compared rules."""
        return round(sum(f.monthly_savings or 0 for f in self._previous_compared()), 2)

    @property
    def current_monthly(self) -> float:
        return round(sum(f.savings_eur or 0 for f in (*self.new, *self.unchanged)), 2)

    @property
    def monthly_change(self) -> float:
        return round(self.current_monthly - self.previous_monthly, 2)

    @property
    def new_monthly(self) -> float:
        return round(sum(f.savings_eur or 0 for f in self.new), 2)

    @property
    def resolved_monthly(self) -> float:
        return round(sum(f.monthly_savings or 0 for f in self.resolved), 2)

    @property
    def changed(self) -> tuple[Finding, ...]:
        """Unchanged findings whose monthly savings changed (e.g. more instances, a new price)."""
        return tuple(f for f in self.unchanged if round(self._delta(f), 2) != 0)

    @property
    def changed_monthly(self) -> float:
        return round(sum(self._delta(f) for f in self.unchanged), 2)

    def status(self, f: Finding) -> TrendStatus:
        return "unchanged" if _key(f) in self.previous_savings else "new"

    def previous_amount(self, f: Finding) -> float | None:
        return self.previous_savings.get(_key(f))

    def rows(self) -> list[TrendRow]:
        """New (highest savings first), resolved (highest first), then changed (biggest change first)."""
        new = sorted(self.new, key=lambda f: f.savings_eur or 0, reverse=True)
        resolved = sorted(self.resolved, key=lambda f: f.monthly_savings or 0, reverse=True)
        changed = sorted(self.changed, key=lambda f: abs(self._delta(f)), reverse=True)
        return [
            *(TrendRow("new", f.name, f.rule, f.subscription_id, None, f.savings_eur) for f in new),
            *(TrendRow("resolved", f.name, f.rule, f.subscription_id, f.monthly_savings, None) for f in resolved),
            *(
                TrendRow("changed", f.name, f.rule, f.subscription_id, self.previous_amount(f), f.savings_eur)
                for f in changed
            ),
        ]

    def _delta(self, f: Finding) -> float:
        return (f.savings_eur or 0) - (self.previous_amount(f) or 0)

    def _previous_compared(self) -> list[PreviousFinding]:
        keys = {_key(f) for f in self.unchanged}
        return [f for f in self.previous.findings if f.key in keys] + list(self.resolved)


def compare(previous: PreviousReport, findings: list[Finding], rules: Iterable[str]) -> Trend:
    """Compare this run's reported findings with the previous report, limited to the rules that ran now."""
    compared_rules = set(rules)
    before = {f.key: f for f in previous.findings if f.rule in compared_rules}
    now_keys = {_key(f) for f in findings}
    return Trend(
        previous=previous,
        new=tuple(f for f in findings if _key(f) not in before),
        resolved=tuple(f for key, f in before.items() if key not in now_keys),
        unchanged=tuple(f for f in findings if _key(f) in before),
        previous_savings={_key(f): before[_key(f)].monthly_savings for f in findings if _key(f) in before},
    )
