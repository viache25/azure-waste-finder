from waste_finder.demo import demo_runner
from waste_finder.rules import RULES, find_waste, load_query


def test_every_rule_has_a_query():
    for rule in RULES:
        assert "Resources" in load_query(rule)


def test_stopped_vm_query_ignores_deallocated():
    q = load_query("stopped_vm")
    assert "PowerState/stopped" in q
    assert "PowerState/deallocated" not in q


def test_find_waste_maps_rows_to_findings():
    findings = find_waste(demo_runner())
    by_rule = {r: [f for f in findings if f.rule == r] for r in RULES}
    assert all(len(v) == 2 for v in by_rule.values())

    disk = next(f for f in by_rule["unattached_disk"] if f.name == "awf-orphaned-disk")
    assert disk.sku == "Standard_LRS" and disk.size_gb == 32
    vm = next(f for f in by_rule["stopped_vm"] if f.name == "awf-stopped-vm")
    assert vm.sku == "Standard_B1s" and vm.os_type == "Linux"


def test_find_waste_with_empty_subscription():
    assert find_waste(lambda query: []) == []
