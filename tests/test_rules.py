import pytest

from waste_finder.demo import demo_runner
from waste_finder.models import Finding
from waste_finder.registry import REGISTRY
from waste_finder.rules import Scope, find_waste, is_too_young, load_query


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
    assert {r: len(v) for r, v in by_rule.items()} == {
        "unattached_disk": 2,
        "stopped_vm": 2,
        "orphaned_public_ip": 3,
        "old_snapshot": 4,  # no minimum age given: all snapshots
        "empty_app_service_plan": 2,
        "idle_nat_gateway": 1,
        "idle_load_balancer": 2,
    }

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


def test_old_snapshot_query_projects_age_and_size():
    q = load_query("old_snapshot")
    assert "microsoft.compute/snapshots" in q
    assert "ageDays" in q and "sizeGb" in q


def test_snapshots_younger_than_min_age_are_not_findings():
    findings = find_waste(demo_runner(), ["old_snapshot"], {"old_snapshot": 30})
    assert sorted(f.name for f in findings) == ["awf-old-snapshot", "erp-db-before-migration", "web-os-before-upgrade"]
    snapshot = next(f for f in findings if f.name == "awf-old-snapshot")
    assert (snapshot.sku, snapshot.size_gb, snapshot.age_days) == ("Standard_LRS", 32, 45)


@pytest.mark.parametrize(("min_age", "count"), [(0, 4), (45, 3), (46, 2), (1000, 0)])
def test_min_age_is_inclusive(min_age, count):
    assert len(find_waste(demo_runner(), ["old_snapshot"], {"old_snapshot": min_age})) == count


def test_min_age_applies_only_to_its_rule_and_rows_with_an_age():
    assert not is_too_young({"ageDays": None}, 30)
    assert not is_too_young({}, 30)
    assert not is_too_young({"ageDays": 5}, None)
    assert is_too_young({"ageDays": 5}, 30)
    findings = find_waste(demo_runner(), ["stopped_vm", "old_snapshot"], {"old_snapshot": 1000})
    assert {f.rule for f in findings} == {"stopped_vm"}


def test_empty_app_service_plan_query_skips_free_and_consumption_tiers():
    q = load_query("empty_app_service_plan")
    assert "microsoft.web/serverfarms" in q and "numberOfSites" in q
    for tier in ("Free", "Shared", "Dynamic", "FlexConsumption"):
        assert f"'{tier}'" in q
    plan = next(f for f in find_waste(demo_runner(), ["empty_app_service_plan"]) if f.name == "asp-intranet-legacy")
    assert (plan.sku, plan.os_type, plan.quantity) == ("S1", "Windows", 2)


def test_idle_network_queries():
    nat = load_query("idle_nat_gateway")
    assert "microsoft.network/natgateways" in nat and "properties.subnets" in nat
    lb = load_query("idle_load_balancer")
    assert "microsoft.network/loadbalancers" in lb and "=~ 'Standard'" in lb
    assert "backendIPConfigurations" in lb and "loadBalancerBackendAddresses" in lb
    assert "loadBalancingRules" in lb and "outboundRules" in lb and "quantity = rules" in lb
    lbs = {f.name: f for f in find_waste(demo_runner(), ["idle_load_balancer"])}
    assert (lbs["lb-web-old"].quantity, lbs["awf-idle-lb"].quantity) == (2, 0)
