"""Every registry entry must be complete: KQL file, pricing strategy, demo fixture rows, texts."""

import json
from importlib import resources

import pytest

from waste_finder.pricing import STRATEGIES
from waste_finder.registry import REGISTRY, SEVERITIES

PACKAGE = resources.files("waste_finder")
DEMO_ROWS = json.loads(PACKAGE.joinpath("demo", "resource_graph.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("rule", REGISTRY.values(), ids=list(REGISTRY))
def test_rule_has_kql_file(rule):
    assert PACKAGE.joinpath("queries", rule.query_file).is_file()


@pytest.mark.parametrize("rule", REGISTRY.values(), ids=list(REGISTRY))
def test_rule_has_pricing_strategy(rule):
    assert rule.pricing in STRATEGIES


@pytest.mark.parametrize("rule", REGISTRY.values(), ids=list(REGISTRY))
def test_rule_has_demo_fixture_rows(rule):
    assert DEMO_ROWS.get(rule.id), f"add rows for {rule.id} to demo/resource_graph.json"


@pytest.mark.parametrize("rule", REGISTRY.values(), ids=list(REGISTRY))
def test_rule_is_fully_described(rule):
    assert rule.severity in SEVERITIES
    assert all([rule.title_de, rule.title_en, rule.why_de, rule.action_de])
    assert rule.docs_url.startswith("https://learn.microsoft.com/")
    assert rule.command.startswith("az ") and ("{id}" in rule.command or "{name}" in rule.command)
    assert rule.remediation_command("/subscriptions/s/resourceGroups/rg").startswith("az ")


def test_registry_keys_match_rule_ids():
    assert all(key == rule.id for key, rule in REGISTRY.items())


def test_no_unused_kql_files_or_strategies():
    kql_files = {p.name for p in PACKAGE.joinpath("queries").iterdir() if p.name.endswith(".kql")}
    assert kql_files == {r.query_file for r in REGISTRY.values()}
    assert set(STRATEGIES) == {r.pricing for r in REGISTRY.values()}


def test_remediation_command_inserts_resource_id():
    cmd = REGISTRY["stopped_vm"].remediation_command("/subscriptions/x/vm1")
    assert cmd == "az vm deallocate --ids /subscriptions/x/vm1"


def test_remediation_command_fills_name_and_subscription():
    cmd = REGISTRY["empty_resource_group"].remediation_command("/subscriptions/sub-1/resourceGroups/rg-old")
    assert cmd == "az group delete --name rg-old --subscription sub-1"
    assert REGISTRY["empty_resource_group"].remediation_command("rg-x") == "az group delete --name rg-x --subscription "


def test_free_rules_are_info():
    for rule in REGISTRY.values():
        assert (rule.pricing == "free") <= (rule.severity == "info")
