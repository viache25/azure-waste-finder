#!/usr/bin/env python3
"""Generate the Azure Workbook workbooks/waste-finder.workbook.json from the rule registry and the KQL files.

    python scripts/build_workbook.py            # (re)write the workbook after changing a rule or a KQL file
    python scripts/build_workbook.py --check    # exit 1 when the committed workbook is out of date

The workbook runs exactly the queries in src/waste_finder/queries/ against Azure Resource Graph: each query is the
KQL file unchanged plus a tail that does in KQL what the CLI does in Python (drop resources tagged
waste-finder:ignore=true, drop age-based rows below the minimum age, add the remediation command). It shows the
affected resources, not euro amounts: prices come from the Retail Prices API / Cost Management, which a workbook
cannot call. tests/test_workbook.py fails when the committed file differs from what this script generates, so the
workbook cannot drift from queries/.
"""

from __future__ import annotations

import argparse
import json
import string
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from waste_finder.config import IGNORE_TAG, Settings
from waste_finder.registry import REGISTRY, SEVERITIES, Rule
from waste_finder.rules import load_query

ROOT = Path(__file__).resolve().parent.parent
WORKBOOK = ROOT / "workbooks" / "waste-finder.workbook.json"

RESOURCE_GRAPH = "microsoft.resourcegraph/resources"
QUERY_TYPE_RESOURCE_GRAPH = 1  # KqlItem queryType for Azure Resource Graph
SUBSCRIPTION_PARAMETER = "Subscription"

# Age-based rules: rule id -> (workbook parameter, label). Defaults come from config.Settings, like the CLI's.
AGE_PARAMETERS = {
    "old_snapshot": ("SnapshotMinAge", "Snapshots älter als (Tage)"),
    "premium_disk_deallocated_vm": ("DowngradeLookback", "VM dealloziert seit (Tagen)"),
}

# The ignore tag as it appears in tostring(tags) (compact JSON), matched lower-cased like the CLI's comparison.
IGNORE_TAG_JSON = json.dumps({IGNORE_TAG: "true"}, separators=(",", ":"))[1:-1]

# Placeholders of Rule.command -> KQL expression on the projected columns.
COMMAND_FIELDS = {
    "id": "id",
    "name": "name",  # the last ID segment; every query projects it
    "subscription": "tostring(split(id, '/')[2])",
}


def _id(name: str) -> str:
    """Stable GUID for a workbook element, so regenerating gives the same file."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"https://github.com/viache25/azure-waste-finder/workbook/{name}"))


def _kql_string(text: str) -> str:
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def kql_command(template: str) -> str:
    """Rule.command (e.g. 'az disk delete --ids {id}') as a KQL strcat() over the row's columns."""
    parts: list[str] = []
    for literal, field, _spec, _conversion in string.Formatter().parse(template):
        if literal:
            parts.append(_kql_string(literal))
        if field is not None:
            if field not in COMMAND_FIELDS:
                raise ValueError(f"unknown placeholder {{{field}}} in command {template!r}")
            parts.append(COMMAND_FIELDS[field])
    return f"strcat({', '.join(parts)})"


def workbook_query(rule: Rule) -> str:
    """The rule's KQL file unchanged, plus the filters the CLI applies in Python and the remediation command."""
    tail = [f"| where tolower(tostring(tags)) !contains {_kql_string(IGNORE_TAG_JSON)}"]
    if rule.id in AGE_PARAMETERS:
        parameter = AGE_PARAMETERS[rule.id][0]
        tail.append(f"| where isnull(ageDays) or ageDays >= {{{parameter}}}")
    tail.append(f"| extend command = {kql_command(rule.command)}")
    return load_query(rule.id).rstrip("\n") + "\n" + "\n".join(tail)


def _text(name: str, markdown: str) -> dict[str, Any]:
    return {"type": 1, "content": {"json": markdown}, "name": name}


def _parameters() -> dict[str, Any]:
    defaults = Settings().min_age_days
    parameters: list[dict[str, Any]] = [
        {
            "id": _id(SUBSCRIPTION_PARAMETER),
            "version": "KqlParameterItem/1.0",
            "name": SUBSCRIPTION_PARAMETER,
            "label": "Subscriptions",
            "type": 6,  # subscription picker
            "isRequired": True,
            "multiSelect": True,
            "quote": "'",
            "delimiter": ",",
            "typeSettings": {"additionalResourceOptions": ["value::all"], "includeAll": False, "showDefault": False},
            "defaultValue": "value::all",
        }
    ]
    for rule_id, (name, label) in AGE_PARAMETERS.items():
        parameters.append(
            {
                "id": _id(name),
                "version": "KqlParameterItem/1.0",
                "name": name,
                "label": label,
                "type": 1,  # text
                "isRequired": True,
                "value": str(defaults[rule_id]),
                "typeSettings": {
                    "paramValidationRules": [{"regExp": "^[0-9]+$", "match": True, "message": "Ganze Zahl ≥ 0"}]
                },
            }
        )
    return {
        "type": 9,
        "content": {
            "version": "KqlParameterItem/1.0",
            "parameters": parameters,
            "style": "pills",
            "queryType": QUERY_TYPE_RESOURCE_GRAPH,
            "resourceType": RESOURCE_GRAPH,
        },
        "name": "parameters",
    }


def _rule_text(rule: Rule, heading: str) -> dict[str, Any]:
    markdown = (
        f"{heading} {rule.title_de}\n\n"
        f"**Priorität:** {SEVERITIES[rule.severity]} · **Regel:** `{rule.id}` · [Doku]({rule.docs_url})\n\n"
        f"{rule.why_de}\n\n"
        f"**Empfehlung:** {rule.action_de} Die Spalte `command` enthält den `az`-Befehl je Ressource."
    )
    return _text(f"text - {rule.id}", markdown)


def _rule_query(rule: Rule) -> dict[str, Any]:
    return {
        "type": 3,
        "content": {
            "version": "KqlItem/1.0",
            "query": workbook_query(rule),
            "size": 0,
            "title": f"{rule.title_de} ({rule.id})",
            "noDataMessage": "Keine Funde.",
            "queryType": QUERY_TYPE_RESOURCE_GRAPH,
            "resourceType": RESOURCE_GRAPH,
            "crossComponentResources": [f"{{{SUBSCRIPTION_PARAMETER}}}"],
            "visualization": "table",
            "showExportToExcel": True,
            "gridSettings": {
                "formatters": [{"columnMatch": "^id$", "formatter": 13, "formatOptions": {"showIcon": True}}]
            },
        },
        "name": f"query - {rule.id}",
    }


INTRO = (
    "# Azure Kostencheck: Verschwendung\n\n"
    "Ressourcen, die Geld kosten, aber nichts tun. Das Workbook führt dieselben Azure-Resource-Graph-Abfragen aus "
    "wie das CLI `waste-finder` "
    "([azure-waste-finder](https://github.com/viache25/azure-waste-finder)), eine Tabelle je Regel. "
    f"Ressourcen mit dem Tag `{IGNORE_TAG}=true` sind ausgeblendet.\n\n"
    "Euro-Beträge rechnet nur das CLI (Azure Retail Prices API oder Cost Management): "
    "`waste-finder --subscription <id>` schreibt den Bericht mit den Kosten je Ressource. "
    "Das Workbook ändert nichts; die Befehle erst prüfen, dann ausführen.\n\n"
    "*Generiert von `scripts/build_workbook.py` aus `src/waste_finder/queries/`; nicht von Hand ändern.*"
)

CLEANUP_INTRO = (
    "## Aufräumen (kostenlos)\n\nDiese Ressourcen kosten nichts. Aufräumen schafft Übersicht und vermeidet Fehler."
)


def build_workbook() -> dict[str, Any]:
    paid = [rule for rule in REGISTRY.values() if rule.pricing != "free"]
    free = [rule for rule in REGISTRY.values() if rule.pricing == "free"]
    items: list[dict[str, Any]] = [_text("text - intro", INTRO), _parameters()]
    for rule in paid:
        items += [_rule_text(rule, "##"), _rule_query(rule)]
    items.append(_text("text - cleanup", CLEANUP_INTRO))
    for rule in free:
        items += [_rule_text(rule, "###"), _rule_query(rule)]
    return {
        "version": "Notebook/1.0",
        "items": items,
        "fallbackResourceIds": ["azure monitor"],
        "$schema": "https://github.com/Microsoft/Application-Insights-Workbooks/blob/master/schema/workbook.json",
    }


def render() -> str:
    return json.dumps(build_workbook(), indent=2, ensure_ascii=False) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the Azure Workbook from the rule registry and KQL files.")
    parser.add_argument("--output", type=Path, default=WORKBOOK, help="workbook file (default: %(default)s)")
    parser.add_argument("--check", action="store_true", help="exit 1 if the file differs from the generated one")
    args = parser.parse_args(argv)
    content = render()
    if args.check:
        current = args.output.read_text(encoding="utf-8") if args.output.is_file() else None
        if current != content:
            print(f"{args.output} is out of date: run python scripts/build_workbook.py", file=sys.stderr)
            return 1
        print(f"{args.output} is up to date")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content, encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
