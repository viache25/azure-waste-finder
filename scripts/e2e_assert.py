#!/usr/bin/env python3
"""Check a live waste-finder report against what Terraform deployed (e2e.yml).

    terraform -chdir=infra output -json expected_findings > expected.json
    python scripts/e2e_assert.py --report reports/report.json --expected expected.json --resource-group awf-e2e-rg

Passes (exit 0) when each of the three base rules (unattached disk, stopped VM, orphaned public IP) has a
finding for exactly the resource Terraform created, in that resource group, with a monthly cost above 0.
Exit 1 lists what is missing; e2e.yml retries, because Resource Graph shows new resources and power states
with a delay. Exit 2 for unreadable input.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# rule id -> key of the infra/ output `expected_findings`
BASE_RULES = {
    "unattached_disk": "unattached_disk",
    "stopped_vm": "stopped_vm",
    "orphaned_public_ip": "orphaned_ip",
}

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


@dataclass(frozen=True)
class Check:
    rule: str
    expected_name: str
    ok: bool
    detail: str


def _same(a: object, b: object) -> bool:
    return str(a).lower() == str(b).lower()


def check_rule(rule: str, expected_name: str, report: dict[str, Any], resource_group: str | None = None) -> Check:
    """Is ``expected_name`` reported by ``rule`` (in ``resource_group``) with a monthly cost above 0?"""

    def matches(f: dict[str, Any]) -> bool:
        return (
            f.get("rule") == rule
            and _same(f.get("name"), expected_name)
            and (resource_group is None or _same(f.get("resource_group"), resource_group))
        )

    found = [f for f in report.get("findings", []) if matches(f)]
    if found:
        cost = found[0].get("monthly_cost")
        if cost is None:
            return Check(rule, expected_name, False, "found, but unpriced (Retail Prices API had no matching meter)")
        if float(cost) <= 0:
            return Check(rule, expected_name, False, f"found, but costs {cost}")
        return Check(rule, expected_name, True, f"found, {float(cost):.2f} {report.get('currency', '')} per month")
    if any(matches(f) for f in report.get("cleanup", [])):
        return Check(rule, expected_name, False, "found only as a free clean-up finding (cost 0)")
    return Check(rule, expected_name, False, "not found (yet)")


def check_report(report: dict[str, Any], expected: dict[str, Any], resource_group: str | None = None) -> list[Check]:
    """One check per base rule; raises ValueError for a demo report or a missing expected name."""
    if report.get("demo"):
        raise ValueError("the report comes from --demo, not from the live subscription")
    checks = []
    for rule, key in BASE_RULES.items():
        name = expected.get(key)
        if not name:
            raise ValueError(f"expected_findings has no name for {key!r}")
        checks.append(check_rule(rule, str(name), report, resource_group))
    return checks


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not hold a JSON object")
    return data


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Assert that a live report finds the three base waste resources.")
    p.add_argument("--report", type=Path, required=True, help="report.json of the live run")
    p.add_argument("--expected", type=Path, required=True, help="`terraform output -json expected_findings`")
    p.add_argument("--resource-group", help="Resource group the waste was deployed into")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = _load_json(args.report)
        expected = _load_json(args.expected)
        checks = check_report(report, expected, args.resource_group)
    except (OSError, ValueError) as e:  # json.JSONDecodeError is a ValueError
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USAGE
    for c in checks:
        print(f"{'ok  ' if c.ok else 'FAIL'}  {c.rule:<20} {c.expected_name:<40} {c.detail}")
    failed = [c for c in checks if not c.ok]
    print(f"{len(checks) - len(failed)} of {len(checks)} base rules found with a cost > 0")
    return EXIT_FAILED if failed else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
