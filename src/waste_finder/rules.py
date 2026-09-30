"""Run one Resource Graph query per rule and turn the rows into Findings."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from importlib import resources
from typing import Any, cast

from waste_finder.models import Finding

# rule name -> KQL file in waste_finder/queries
RULES: dict[str, str] = {
    "unattached_disk": "unattached_disks.kql",
    "stopped_vm": "stopped_vms.kql",
    "orphaned_public_ip": "orphaned_public_ips.kql",
}

# One Resource Graph result row.
Row = dict[str, Any]

# A query runner takes KQL and returns a list of row dicts.
QueryRunner = Callable[[str], list[Row]]


def load_query(rule: str) -> str:
    return resources.files("waste_finder").joinpath("queries", RULES[rule]).read_text(encoding="utf-8")


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
    )


def find_waste(run_query: QueryRunner, rules: Iterable[str] = RULES) -> list[Finding]:
    findings: list[Finding] = []
    for rule in rules:
        for row in run_query(load_query(rule)):
            findings.append(row_to_finding(rule, row))
    return findings


def resource_graph_runner(subscription_id: str) -> QueryRunner:
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
            response = client.resources(QueryRequest(subscriptions=[subscription_id], query=query, options=options))
            # SDK types `data` as a mapping; with result_format="objectArray" it is a list of rows.
            rows.extend(cast(list[Row], response.data))
            skip_token = response.skip_token
            if not skip_token:
                return rows

    return run
