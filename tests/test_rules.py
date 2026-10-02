from waste_finder.demo import demo_runner
from waste_finder.models import Finding
from waste_finder.registry import REGISTRY
from waste_finder.rules import Scope, find_waste, load_query


def test_every_rule_has_a_query():
    for rule in REGISTRY:
        assert "Resources" in load_query(rule)


def test_stopped_vm_query_ignores_deallocated():
    q = load_query("stopped_vm")
    assert "PowerState/stopped" in q
    assert "PowerState/deallocated" not in q


def test_find_waste_maps_rows_to_findings():
    findings = find_waste(demo_runner())
    by_rule = {r: [f for f in findings if f.rule == r] for r in REGISTRY}
    assert {r: len(v) for r, v in by_rule.items()} == {"unattached_disk": 2, "stopped_vm": 2, "orphaned_public_ip": 3}

    disk = next(f for f in by_rule["unattached_disk"] if f.name == "awf-orphaned-disk")
    assert disk.sku == "Standard_LRS" and disk.size_gb == 32
    vm = next(f for f in by_rule["stopped_vm"] if f.name == "awf-stopped-vm")
    assert vm.sku == "Standard_B1s" and vm.os_type == "Linux"


def test_find_waste_with_empty_subscription():
    assert find_waste(lambda query: []) == []


def test_findings_carry_the_rule_severity():
    for f in find_waste(demo_runner()):
        assert f.severity == REGISTRY[f.rule].severity


def test_find_waste_runs_only_selected_rules():
    findings = find_waste(demo_runner(), ["stopped_vm"])
    assert {f.rule for f in findings} == {"stopped_vm"}


def test_finding_knows_its_subscription():
    f = find_waste(demo_runner(), ["stopped_vm"])[0]
    assert f.subscription_id == "11111111-1111-1111-1111-111111111111"
    assert Finding("stopped_vm", "not-an-arm-id", "a", "rg", "we", "x").subscription_id == ""


def test_scope_labels():
    assert Scope(subscriptions=("a", "b")).label() == "a, b"
    assert Scope(management_group="mg-prod").label() == "Management Group mg-prod"
    assert Scope().label() == "alle lesbaren Subscriptions"
