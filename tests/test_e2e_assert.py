"""scripts/e2e_assert.py: the assertion step of the live end-to-end test (e2e.yml), on offline reports."""

import json
import runpy
import sys
from pathlib import Path

import pytest

import e2e_assert
from e2e_assert import BASE_RULES, check_report, check_rule, main
from waste_finder.cli import main as finder_main
from waste_finder.registry import REGISTRY

ROOT = Path(__file__).resolve().parent.parent
RG = "awf-waste-demo-rg"
# What `terraform output -json expected_findings` prints for the default prefix (extra waste off).
EXPECTED = {
    "unattached_disk": "awf-orphaned-disk",
    "stopped_vm": "awf-stopped-vm",
    "orphaned_ip": "awf-orphaned-pip",
    "old_snapshot": None,
    "empty_app_service_plan": None,
    "idle_load_balancer": None,
    "orphaned_nic": None,
    "unattached_nsg": None,
    "empty_resource_group": None,
}


@pytest.fixture(scope="module")
def demo_json(tmp_path_factory):
    out = tmp_path_factory.mktemp("demo")
    assert finder_main(["--demo", "--format", "json", "--out-dir", str(out)]) == 0
    return json.loads((out / "report.json").read_text(encoding="utf-8"))


@pytest.fixture
def live_report(demo_json):
    """The demo report contains the awf-* resources Terraform deploys; pretend it came from a live run."""
    report = json.loads(json.dumps(demo_json))
    report["demo"] = False
    return report


def write(tmp_path, name, data):
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def find(report, name):
    return next(f for f in report["findings"] if f["name"] == name)


def test_base_rules_exist_in_the_registry_and_the_terraform_output():
    assert set(BASE_RULES) <= set(REGISTRY)
    outputs = (ROOT / "infra" / "outputs.tf").read_text(encoding="utf-8")
    for key in BASE_RULES.values():
        assert f"    {key} " in outputs, f"infra/outputs.tf expected_findings has no {key}"


def test_all_three_found(live_report):
    checks = check_report(live_report, EXPECTED, RG)
    assert [c.rule for c in checks] == ["unattached_disk", "stopped_vm", "orphaned_public_ip"]
    assert all(c.ok for c in checks)
    assert checks[1].detail == "found, 8.18 EUR per month"


def test_names_and_resource_group_are_case_insensitive(live_report):
    find(live_report, "awf-stopped-vm")["resource_group"] = "AWF-WASTE-DEMO-RG"
    assert all(c.ok for c in check_report(live_report, {**EXPECTED, "stopped_vm": "AWF-Stopped-VM"}, RG))


def test_without_a_resource_group_any_group_matches(live_report):
    assert all(c.ok for c in check_report(live_report, EXPECTED))


def test_other_resource_group_is_not_enough(live_report):
    checks = check_report(live_report, EXPECTED, "awf-e2e-rg")
    assert not any(c.ok for c in checks)
    assert {c.detail for c in checks} == {"not found (yet)"}


def test_missing_finding(live_report):
    live_report["findings"] = [f for f in live_report["findings"] if f["name"] != "awf-stopped-vm"]
    checks = {c.rule: c for c in check_report(live_report, EXPECTED, RG)}
    assert not checks["stopped_vm"].ok and checks["stopped_vm"].detail == "not found (yet)"
    assert checks["unattached_disk"].ok and checks["orphaned_public_ip"].ok


def test_same_name_but_other_rule_does_not_count(live_report):
    find(live_report, "awf-stopped-vm")["rule"] = "premium_disk_deallocated_vm"
    assert not check_rule("stopped_vm", "awf-stopped-vm", live_report, RG).ok


def test_unpriced_finding_fails(live_report):
    find(live_report, "awf-orphaned-pip")["monthly_cost"] = None
    check = check_rule("orphaned_public_ip", "awf-orphaned-pip", live_report, RG)
    assert not check.ok and "unpriced" in check.detail


def test_zero_cost_finding_fails(live_report):
    find(live_report, "awf-orphaned-disk")["monthly_cost"] = 0
    check = check_rule("unattached_disk", "awf-orphaned-disk", live_report, RG)
    assert not check.ok and check.detail == "found, but costs 0"


def test_free_cleanup_finding_fails(live_report):
    disk = find(live_report, "awf-orphaned-disk")
    live_report["findings"].remove(disk)
    live_report["cleanup"].append({**disk, "monthly_cost": 0.0})
    check = check_rule("unattached_disk", "awf-orphaned-disk", live_report, RG)
    assert not check.ok and "free clean-up" in check.detail


def test_demo_report_is_rejected(demo_json):
    with pytest.raises(ValueError, match="--demo"):
        check_report(demo_json, EXPECTED, RG)


def test_expected_name_missing(live_report):
    with pytest.raises(ValueError, match="'orphaned_ip'"):
        check_report(live_report, {**EXPECTED, "orphaned_ip": None}, RG)


def test_main_passes(tmp_path, live_report, capsys):
    report = write(tmp_path, "report.json", live_report)
    expected = write(tmp_path, "expected.json", EXPECTED)
    assert main(["--report", str(report), "--expected", str(expected), "--resource-group", RG]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("ok    unattached_disk") and "awf-orphaned-disk" in out[0]
    assert out[-1] == "3 of 3 base rules found with a cost > 0"


def test_main_fails_with_a_list_of_what_is_missing(tmp_path, live_report, capsys):
    live_report["findings"] = []
    report = write(tmp_path, "report.json", live_report)
    expected = write(tmp_path, "expected.json", EXPECTED)
    assert main(["--report", str(report), "--expected", str(expected)]) == 1
    out = capsys.readouterr().out
    assert out.count("FAIL") == 3 and "0 of 3 base rules" in out


@pytest.mark.parametrize(
    ("report_text", "expected_text", "message"),
    [
        ("not json", json.dumps(EXPECTED), "Expecting value"),
        ("[]", json.dumps(EXPECTED), "does not hold a JSON object"),
        (json.dumps({"demo": True}), json.dumps(EXPECTED), "--demo"),
        (json.dumps({"demo": False}), "{}", "no name for 'unattached_disk'"),
    ],
)
def test_main_usage_errors(tmp_path, capsys, report_text, expected_text, message):
    (tmp_path / "r.json").write_text(report_text, encoding="utf-8")
    (tmp_path / "e.json").write_text(expected_text, encoding="utf-8")
    assert main(["--report", str(tmp_path / "r.json"), "--expected", str(tmp_path / "e.json")]) == 2
    assert message in capsys.readouterr().err


def test_main_missing_file(tmp_path, capsys):
    assert main(["--report", str(tmp_path / "nope.json"), "--expected", str(tmp_path / "nope.json")]) == 2
    assert "error:" in capsys.readouterr().err


def test_script_runs_as_a_program(tmp_path, live_report, monkeypatch, capsys):
    report = write(tmp_path, "report.json", live_report)
    expected = write(tmp_path, "expected.json", EXPECTED)
    monkeypatch.setattr(sys, "argv", ["e2e_assert.py", "--report", str(report), "--expected", str(expected)])
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(e2e_assert.__file__, run_name="__main__")
    assert exit_info.value.code == 0
    assert "3 of 3" in capsys.readouterr().out
