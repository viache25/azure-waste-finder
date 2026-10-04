"""Offline data for --demo and tests: fake subscriptions, a small price list and Cost Management answers."""

from __future__ import annotations

import json
import re
from importlib import resources
from typing import Any

from waste_finder.costs import ActualCosts, CostQuery, parse_query_result
from waste_finder.pricing import PriceFetcher, PriceItem
from waste_finder.registry import REGISTRY
from waste_finder.rules import QueryRunner, Row, load_query


def _load(name: str) -> Any:
    return json.loads(resources.files("waste_finder").joinpath("demo", name).read_text(encoding="utf-8"))


def demo_runner() -> QueryRunner:
    data = _load("resource_graph.json")
    query_to_rule = {load_query(rule): rule for rule in REGISTRY}

    def run(query: str) -> list[Row]:
        rows: list[Row] = data[query_to_rule[query]]
        return rows

    return run


def demo_fetcher() -> PriceFetcher:
    """Evaluates the simple `field eq 'value' and ...` filters we send to the real API."""
    items: list[PriceItem] = _load("prices.json")["Items"]

    def fetch(odata_filter: str) -> list[PriceItem]:
        conditions = re.findall(r"(\w+) eq '([^']*)'", odata_filter)
        return [i for i in items if all(i.get(k) == v for k, v in conditions)]

    return fetch


def demo_cost_query() -> CostQuery:
    """Recorded-format Cost Management answers per demo subscription (--demo --cost-source actual)."""
    responses = _load("cost_management.json")

    def query(subscription_id: str) -> ActualCosts:
        return parse_query_result(responses[subscription_id]) if subscription_id in responses else {}

    return query
