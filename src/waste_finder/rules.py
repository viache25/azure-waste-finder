"""Run one Resource Graph query per rule and turn the rows into Findings."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from importlib import resources
from typing import Any, cast

from waste_finder.models import Finding
from waste_finder.registry import REGISTRY

# One Resource Graph result row.
Row = dict[str, Any]

# A query runner takes KQL and returns a list of row dicts.
QueryRunner = Callable[[str], list[Row]]


def load_query(rule: str) -> str:
    return resources.files("waste_finder").joinpath("queries", REGISTRY[rule].query_file).read_text(encoding="utf-8")


def row_to_finding(rule: str, row: Row) -> Finding:
    return Finding(
        rule=rule,
        resource_id=row["id"],
        name=row["name"],
        resource_group=row.get("resourceGroup", ""),
        location=row.get("location", ""),
        sku=row.get("sku") or "",
        size_gb=row.get("sizeGb"),
        os_type=row.get("osType"),
        tags=row.get("tags") or {},
        severity=REGISTRY[rule].severity,
    )


def find_waste(run_query: QueryRunner, rules: Iterable[str] = REGISTRY) -> list[Finding]:
    findings: list[Finding] = []
    for rule in rules:
        for row in run_query(load_query(rule)):
            findings.append(row_to_finding(rule, row))
    return findings


@dataclass(frozen=True)
class Scope:
    """What Resource Graph searches: given subscriptions, one management group, or (neither) every
    subscription the credential can read."""

    subscriptions: tuple[str, ...] = ()
    management_group: str | None = None

    def label(self) -> str:
        """For the report header (German)."""
        if self.management_group:
            return f"Management Group {self.management_group}"
        return ", ".join(self.subscriptions) or "alle lesbaren Subscriptions"


def resource_graph_runner(scope: Scope) -> QueryRunner:
    """Real runner: Azure Resource Graph, authenticated via DefaultAzureCredential (az login)."""
    from azure.identity import DefaultAzureCredential
    from azure.mgmt.resourcegraph import ResourceGraphClient
    from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions

    client = ResourceGraphClient(DefaultAzureCredential())

    def run(query: str) -> list[Row]:
        rows: list[Row] = []
        skip_token = None
        while True:
            options = QueryRequestOptions(result_format="objectArray", skip_token=skip_token)
            # Neither subscriptions nor management groups = every subscription the credential can read.
            request = QueryRequest(
                subscriptions=list(scope.subscriptions) or None,
                management_groups=[scope.management_group] if scope.management_group else None,
                query=query,
                options=options,
            )
            response = client.resources(request)
            # SDK types `data` as a mapping; with result_format="objectArray" it is a list of rows.
            rows.extend(cast(list[Row], response.data))
            skip_token = response.skip_token
            if not skip_token:
                return rows

    return run
