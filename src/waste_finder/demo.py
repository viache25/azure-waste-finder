"""Offline data for --demo and tests: a fake subscription and a small price list."""
from __future__ import annotations

import json
import re
from importlib import resources

from waste_finder.pricing import PriceFetcher
from waste_finder.rules import RULES, QueryRunner, load_query


def _load(name: str) -> dict:
    return json.loads(resources.files("waste_finder").joinpath("demo", name).read_text(encoding="utf-8"))


def demo_runner() -> QueryRunner:
    data = _load("resource_graph.json")
    query_to_rule = {load_query(rule): rule for rule in RULES}

    def run(query: str) -> list[dict]:
        return data[query_to_rule[query]]

    return run


def demo_fetcher() -> PriceFetcher:
    """Evaluates the simple `field eq 'value' and ...` filters we send to the real API."""
    items = _load("prices.json")["Items"]

    def fetch(odata_filter: str) -> list[dict]:
        conditions = re.findall(r"(\w+) eq '([^']*)'", odata_filter)
        return [i for i in items if all(i.get(k) == v for k, v in conditions)]

    return fetch
