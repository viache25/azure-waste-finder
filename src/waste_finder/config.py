"""Settings from an optional waste-finder.toml, overridden by CLI flags.

Example file:

    rules = ["unattached_disk", "stopped_vm"]       # default: all rules
    exclude = ["/subscriptions/*/resourceGroups/rg-sandbox/*"]
    currency = "EUR"
    formats = ["md", "html", "json"]                 # default: md, html

    [thresholds]
    min_monthly_savings = 1.0                        # leave out findings that save less per month
    fail_over = 100                                  # exit code 3 when the monthly total is higher
    snapshot_min_age_days = 30                       # old_snapshot: report snapshots at least this old
    downgrade_lookback_days = 30                     # premium_disk_deallocated_vm: VM deallocated this long
"""

from __future__ import annotations

import fnmatch
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from waste_finder.export import DEFAULT_FORMATS, FORMATS
from waste_finder.models import Finding
from waste_finder.registry import REGISTRY

CONFIG_FILE = Path("waste-finder.toml")

# Resources with this tag set to "true" are never reported as waste.
IGNORE_TAG = "waste-finder:ignore"

# Currencies the Retail Prices API accepts as `currencyCode`.
CURRENCIES = frozenset(
    {"USD", "AUD", "BRL", "CAD", "CHF", "CNY", "DKK", "EUR", "GBP", "INR", "JPY", "KRW", "NOK", "NZD", "SEK", "TWD"}
)

TOP_LEVEL_KEYS = {"rules", "exclude", "currency", "formats", "thresholds"}
THRESHOLD_KEYS = {"min_monthly_savings", "fail_over", "snapshot_min_age_days", "downgrade_lookback_days"}


class ConfigError(ValueError):
    """Invalid config file or CLI value; the CLI prints it and exits with code 2."""


@dataclass(frozen=True)
class Settings:
    rules: tuple[str, ...] = tuple(REGISTRY)
    exclude: tuple[str, ...] = ()  # glob patterns on the resource ID, case-insensitive
    min_monthly_savings: float = 0.0
    currency: str = "EUR"
    formats: tuple[str, ...] = DEFAULT_FORMATS
    fail_over: float | None = None  # exit code 3 when the monthly total is above this
    snapshot_min_age_days: int = 30  # old_snapshot reports snapshots at least this many days old
    downgrade_lookback_days: int = 30  # premium_disk_deallocated_vm: VM deallocated for at least this many days
    source: str = field(default="defaults", compare=False)  # where the file values came from, for messages

    @property
    def min_age_days(self) -> dict[str, int]:
        """Rule id -> minimum age in days for the age-based rules (rules.find_waste)."""
        return {
            "old_snapshot": self.snapshot_min_age_days,
            "premium_disk_deallocated_vm": self.downgrade_lookback_days,
        }


def parse_rules(value: Iterable[str]) -> tuple[str, ...]:
    rules = tuple(r.strip() for r in value if r.strip())
    unknown = [r for r in rules if r not in REGISTRY]
    if unknown:
        raise ConfigError(f"unknown rule(s): {', '.join(unknown)} (known: {', '.join(REGISTRY)})")
    if not rules:
        raise ConfigError("no rules selected")
    return rules


def parse_currency(value: str) -> str:
    currency = value.upper()
    if currency not in CURRENCIES:
        raise ConfigError(f"unsupported currency {value!r} (supported: {', '.join(sorted(CURRENCIES))})")
    return currency


def parse_formats(value: Iterable[str]) -> tuple[str, ...]:
    formats = tuple(dict.fromkeys(f.strip().lower() for f in value if f.strip()))
    unknown = [f for f in formats if f not in FORMATS]
    if unknown:
        raise ConfigError(f"unknown format(s): {', '.join(unknown)} (known: {', '.join(FORMATS)})")
    if not formats:
        raise ConfigError("no output format selected")
    return formats


def parse_amount(value: Any, name: str = "min_monthly_savings") -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise ConfigError(f"{name} must be a number >= 0, got {value!r}")
    return float(value)


def parse_min_savings(value: Any) -> float:
    return parse_amount(value, "min_monthly_savings")


def parse_fail_over(value: Any) -> float:
    return parse_amount(value, "fail_over")


def parse_days(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ConfigError(f"{name} must be a whole number of days >= 0, got {value!r}")
    return value


def parse_snapshot_min_age(value: Any) -> int:
    return parse_days(value, "snapshot_min_age_days")


def parse_downgrade_lookback(value: Any) -> int:
    return parse_days(value, "downgrade_lookback_days")


def _string_list(data: Mapping[str, Any], key: str) -> list[str]:
    value = data[key]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{key} must be a list of strings")
    return value


def load_config(path: Path) -> dict[str, Any]:
    """Read and validate a config file; returns the Settings fields it sets."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise ConfigError(f"cannot read {path}: {e}") from e

    unknown = set(data) - TOP_LEVEL_KEYS
    if unknown:
        raise ConfigError(f"{path}: unknown key(s): {', '.join(sorted(unknown))}")

    values: dict[str, Any] = {}
    if "rules" in data:
        values["rules"] = parse_rules(_string_list(data, "rules"))
    if "exclude" in data:
        values["exclude"] = tuple(_string_list(data, "exclude"))
    if "currency" in data:
        if not isinstance(data["currency"], str):
            raise ConfigError("currency must be a string")
        values["currency"] = parse_currency(data["currency"])
    if "formats" in data:
        values["formats"] = parse_formats(_string_list(data, "formats"))
    if "thresholds" in data:
        thresholds = data["thresholds"]
        if not isinstance(thresholds, dict) or set(thresholds) - THRESHOLD_KEYS:
            raise ConfigError(f"[thresholds] supports only: {', '.join(sorted(THRESHOLD_KEYS))}")
        if "min_monthly_savings" in thresholds:
            values["min_monthly_savings"] = parse_min_savings(thresholds["min_monthly_savings"])
        if "fail_over" in thresholds:
            values["fail_over"] = parse_fail_over(thresholds["fail_over"])
        if "snapshot_min_age_days" in thresholds:
            values["snapshot_min_age_days"] = parse_snapshot_min_age(thresholds["snapshot_min_age_days"])
        if "downgrade_lookback_days" in thresholds:
            values["downgrade_lookback_days"] = parse_downgrade_lookback(thresholds["downgrade_lookback_days"])
    return values


def resolve_settings(config_path: Path | None, overrides: Mapping[str, Any]) -> Settings:
    """Defaults < config file < CLI flags. `overrides` holds CLI values, None = flag not given.

    Without an explicit path, ./waste-finder.toml is used if it exists.
    """
    path = config_path or (CONFIG_FILE if CONFIG_FILE.is_file() else None)
    values = load_config(path) if path else {}
    values.update({k: v for k, v in overrides.items() if v is not None})
    return Settings(**values, source=str(path) if path else "defaults")


def is_ignored(finding: Finding, exclude: Iterable[str] = ()) -> bool:
    """True if the resource carries waste-finder:ignore=true or its ID matches an exclude pattern."""
    tags = {k.lower(): str(v).strip().lower() for k, v in finding.tags.items()}
    if tags.get(IGNORE_TAG) == "true":
        return True
    resource_id = finding.resource_id.lower()
    return any(fnmatch.fnmatchcase(resource_id, pattern.lower()) for pattern in exclude)


def split_ignored(findings: list[Finding], exclude: Iterable[str] = ()) -> tuple[list[Finding], list[Finding]]:
    """-> (findings to report, ignored findings)."""
    patterns = tuple(exclude)
    kept = [f for f in findings if not is_ignored(f, patterns)]
    ignored = [f for f in findings if is_ignored(f, patterns)]
    return kept, ignored


def split_free(findings: list[Finding]) -> tuple[list[Finding], list[Finding]]:
    """-> (findings that cost money or are unpriced, free clean-up findings priced at exactly 0)."""
    return [f for f in findings if not f.is_free], [f for f in findings if f.is_free]


def split_below_threshold(findings: list[Finding], min_savings: float) -> tuple[list[Finding], list[Finding]]:
    """-> (findings at or above the threshold, findings below it). Unpriced findings are always kept."""

    def is_below(f: Finding) -> bool:
        return f.savings_eur is not None and f.savings_eur < min_savings

    return [f for f in findings if not is_below(f)], [f for f in findings if is_below(f)]
