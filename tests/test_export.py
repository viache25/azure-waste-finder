"""JSON / CSV / SARIF output, the Markdown summary and the --fail-over exit code."""

import csv
import io
import json
from pathlib import Path

import jsonschema
import pytest

from waste_finder.cli import EXIT_OVER_THRESHOLD, main
from waste_finder.export import (
    CSV_COLUMNS,
    SCHEMA_VERSION,
    RunInfo,
    render_csv,
    render_json,
    render_sarif,
    render_summary,
)
from waste_finder.models import Finding
from waste_finder.registry import REGISTRY
from waste_finder.report import render, summarize

SCHEMA = json.loads((Path(__file__).parent.parent / "docs" / "report.schema.json").read_text(encoding="utf-8"))
SUB = "/subscriptions/s1/resourceGroups/rg/providers/Microsoft.Compute"


def findings():
    return [
        Finding("unattached_disk", f"{SUB}/disks/d1", "d1", "rg", "we", "LRS", size_gb=32, monthly_cost_eur=1.5),
        Finding(
            "stopped_vm", f"{SUB}/virtualMachines/vm1", "vm1", "rg", "we", "B", severity="high", monthly_cost_eur=9.0
        ),
        Finding("orphaned_public_ip", f"{SUB}/publicIPAddresses/p", "p", "rg", "we", "Standard", severity="low"),
    ]


@pytest.fixture
def demo_reports(tmp_path):
    assert main(["--demo", "--format", "md,html,json,csv,sarif", "--out-dir", str(tmp_path)]) == 0
    return tmp_path


def test_all_formats_are_written(demo_reports):
    assert sorted(p.name for p in demo_reports.iterdir()) == [
        "report.csv",
        "report.html",
        "report.json",
        "report.md",
        "report.sarif",
    ]


def test_default_formats_are_md_and_html(tmp_path):
    assert main(["--demo", "--out-dir", str(tmp_path)]) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["report.html", "report.md"]


def test_demo_json_matches_schema(demo_reports):
    data = json.loads((demo_reports / "report.json").read_text(encoding="utf-8"))
    jsonschema.validate(data, SCHEMA, format_checker=jsonschema.FormatChecker())
    assert data["schema_version"] == SCHEMA_VERSION
    assert data["demo"] is True and data["currency"] == "EUR"
    assert data["summary"]["monthly_savings"] == 509.03 and data["summary"]["ignored"] == 1
    assert len(data["findings"]) == data["summary"]["count"] == 15
    assert len(data["cleanup"]) == data["summary"]["cleanup"] == 6
    savings = [f["monthly_savings"] for f in data["findings"]]
    assert savings == sorted(savings, reverse=True)


def test_json_with_unpriced_and_downgrade_matches_schema():
    fs = findings()
    fs[0].monthly_savings_eur = 0.5
    text = render_json(fs, summarize(fs), RunInfo("subscription s1", "CHF", min_monthly_savings=1))
    data = json.loads(text)
    jsonschema.validate(data, SCHEMA)
    by_name = {f["name"]: f for f in data["findings"]}
    assert (by_name["d1"]["monthly_cost"], by_name["d1"]["monthly_savings"]) == (1.5, 0.5)
    assert by_name["p"]["monthly_cost"] is None and by_name["p"]["subscription_id"] == "s1"
    assert by_name["vm1"]["command"] == f"az vm deallocate --ids {SUB}/virtualMachines/vm1"
    assert data["summary"]["unpriced"] == 1 and data["currency"] == "CHF"


def test_schema_rejects_unknown_fields():
    data = json.loads(render_json([], summarize([]), RunInfo("x")))
    data["unexpected"] = 1
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(data, SCHEMA)


def test_csv_has_one_row_per_finding():
    fs = findings()
    rows = list(csv.DictReader(io.StringIO(render_csv(fs, summarize(fs), RunInfo("x", "USD")))))
    assert tuple(rows[0]) == CSV_COLUMNS
    assert [r["name"] for r in rows] == ["vm1", "d1", "p"]
    assert rows[0]["monthly_cost"] == "9.0" and rows[0]["currency"] == "USD" and rows[0]["size_gb"] == ""
    assert rows[1]["size_gb"] == "32" and rows[1]["monthly_cost"] == "1.5"
    assert rows[2]["monthly_cost"] == "" and rows[2]["title"] == "Orphaned public IP"


def test_sarif_structure(demo_reports):
    sarif = json.loads((demo_reports / "report.sarif").read_text(encoding="utf-8"))
    assert sarif["version"] == "2.1.0"
    (run,) = sarif["runs"]
    rules = run["tool"]["driver"]["rules"]
    assert [r["id"] for r in rules] == list(REGISTRY)
    assert all(r["helpUri"].startswith("https://learn.microsoft.com/") for r in rules)
    assert len(run["results"]) == 21  # 15 findings + 6 free clean-up findings
    for result in run["results"]:
        assert rules[result["ruleIndex"]]["id"] == result["ruleId"]
        location = result["locations"][0]
        resource_id = location["logicalLocations"][0]["fullyQualifiedName"]
        assert location["physicalLocation"]["artifactLocation"]["uri"] == resource_id.lstrip("/")
        command = result["properties"]["command"]
        assert command.endswith(resource_id) or f"--name {resource_id.rsplit('/', 1)[-1]} " in command
    vm = next(r for r in run["results"] if "build-agent-02" in r["message"]["text"])
    assert vm["level"] == "error" and "148,19 €" in vm["message"]["text"]


def test_sarif_levels_and_stable_fingerprints():
    fs = findings()
    first = json.loads(render_sarif(fs, summarize(fs), RunInfo("x")))["runs"][0]["results"]
    again = json.loads(render_sarif(fs[::-1], summarize(fs), RunInfo("x")))["runs"][0]["results"]
    assert {r["ruleId"]: r["level"] for r in first} == {
        "stopped_vm": "error",
        "unattached_disk": "warning",
        "orphaned_public_ip": "note",
    }
    prints = [r["partialFingerprints"]["resourceRule/v1"] for r in first]
    assert len(set(prints)) == 3
    assert prints == [r["partialFingerprints"]["resourceRule/v1"] for r in again]


def test_summary_markdown():
    fs = findings()
    text = render_summary(fs, summarize(fs, ignored=2), RunInfo("subscription s1"), fail_over=5)
    assert text.startswith("### Azure Kostencheck: ca. 10,50 € pro Monat")
    assert "Schwelle 5,00 € pro Monat: **überschritten**" in text
    assert text.index("VM gestoppt") < text.index("Nicht angehängte Managed Disk")
    assert "1 ohne Preis, 2 ignoriert" in text
    assert text.endswith("\n\n")


def test_summary_without_findings_or_threshold():
    text = render_summary([], summarize([]), RunInfo("x"))
    assert "**0** ungenutzte" in text and "Schwelle" not in text and "|" not in text


def test_summary_is_appended(tmp_path):
    summary = tmp_path / "step-summary.md"
    summary.write_text("# Earlier step\n", encoding="utf-8")
    args = ["--demo", "--out-dir", str(tmp_path / "out"), "--summary", str(summary), "--fail-over", "600"]
    assert main(args) == 0
    text = summary.read_text(encoding="utf-8")
    assert text.startswith("# Earlier step\n### Azure Kostencheck: ca. 509,03 €")
    assert "**eingehalten**" in text


def test_empty_summary_path_is_skipped(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["--demo", "--out-dir", "out", "--summary", ""]) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out"]


@pytest.mark.parametrize(("fail_over", "code"), [("509.03", 0), ("509", EXIT_OVER_THRESHOLD), ("0", 3)])
def test_fail_over_exit_code(tmp_path, capsys, fail_over, code):
    assert main(["--demo", "--out-dir", str(tmp_path), "--fail-over", fail_over]) == code
    assert ("above --fail-over" in capsys.readouterr().err) == (code == 3)
    assert (tmp_path / "report.md").exists()  # reports are written either way


def test_fail_over_from_config_file(tmp_path):
    config = tmp_path / "waste-finder.toml"
    config.write_text('formats = ["json"]\n[thresholds]\nfail_over = 100\n', encoding="utf-8")
    assert main(["--demo", "--config", str(config), "--out-dir", str(tmp_path / "out")]) == 3
    assert [p.name for p in (tmp_path / "out").iterdir()] == ["report.json"]


def test_snapshot_age_in_json_csv_and_report(demo_reports):
    data = json.loads((demo_reports / "report.json").read_text(encoding="utf-8"))
    by_name = {f["name"]: f for f in data["findings"]}
    assert by_name["awf-old-snapshot"]["age_days"] == 45 and by_name["awf-old-snapshot"]["rule"] == "old_snapshot"
    assert by_name["awf-stopped-vm"]["age_days"] is None
    rows = {
        r["name"]: r for r in csv.DictReader(io.StringIO((demo_reports / "report.csv").read_text(encoding="utf-8")))
    }
    assert rows["erp-db-before-migration"]["age_days"] == "324" and rows["awf-stopped-vm"]["age_days"] == ""
    for fmt in ("md", "html"):
        assert "Standard_LRS (32 GB), 45 Tage alt" in (demo_reports / f"report.{fmt}").read_text(encoding="utf-8")


def test_schema_still_accepts_1_0_reports_without_age():
    data = json.loads(render_json(findings(), summarize(findings()), RunInfo("x")))
    data["schema_version"] = "1.0"
    for f in data["findings"]:
        del f["age_days"], f["quantity"], f["cost_source"], f["trend"], f["previous_monthly_savings"]
    del data["cleanup"], data["summary"]["cleanup"], data["summary"]["actual_costs"]
    del data["cost_source"], data["cost_period"], data["trend"]
    jsonschema.validate(data, SCHEMA)


def test_plan_instances_in_json_csv_and_report(demo_reports):
    data = json.loads((demo_reports / "report.json").read_text(encoding="utf-8"))
    by_name = {f["name"]: f for f in data["findings"]}
    assert by_name["asp-intranet-legacy"]["quantity"] == 2 and by_name["awf-stopped-vm"]["quantity"] is None
    rows = {r["name"]: r for r in csv.DictReader(io.StringIO((demo_reports / "report.csv").read_text("utf-8")))}
    assert rows["asp-intranet-legacy"]["quantity"] == "2" and rows["erp-db-old-data"]["quantity"] == ""
    for fmt in ("md", "html"):
        assert "S1, 2 Instanz(en)" in (demo_reports / f"report.{fmt}").read_text(encoding="utf-8")


def test_quantity_needs_a_unit_to_be_shown():
    f = Finding("stopped_vm", f"{SUB}/virtualMachines/vm1", "vm1", "rg", "we", "B1s", quantity=3, monthly_cost_eur=1)
    assert "B1s, 3" not in render([f], "x", "md")


def test_load_balancer_without_rules_is_a_free_info_finding(demo_reports):
    data = json.loads((demo_reports / "report.json").read_text(encoding="utf-8"))
    assert all(f["name"] != "awf-idle-lb" for f in data["findings"])
    lb = next(f for f in data["cleanup"] if f["name"] == "awf-idle-lb")
    assert (lb["severity"], lb["monthly_cost"], lb["quantity"]) == ("info", 0.0, 0)
    sarif = json.loads((demo_reports / "report.sarif").read_text(encoding="utf-8"))
    result = next(r for r in sarif["runs"][0]["results"] if "awf-idle-lb" in r["message"]["text"])
    assert result["level"] == "note"


def test_cleanup_findings_in_exports_but_not_in_the_total(demo_reports):
    data = json.loads((demo_reports / "report.json").read_text(encoding="utf-8"))
    cleanup = data["cleanup"]
    assert {f["rule"] for f in cleanup} == {
        "orphaned_nic",
        "unattached_nsg",
        "empty_resource_group",
        "idle_load_balancer",
    }
    assert all(f["monthly_cost"] == 0.0 and f["severity"] == "info" for f in cleanup)
    assert [f["subscription_id"][:4] for f in cleanup] == ["0000"] * 4 + ["1111"] * 2  # sorted by subscription
    assert data["summary"]["monthly_savings"] == round(sum(f["monthly_savings"] for f in data["findings"]), 2)
    rows = list(csv.DictReader(io.StringIO((demo_reports / "report.csv").read_text("utf-8"))))
    assert len(rows) == 21 and [r["name"] for r in rows[-6:]] == [f["name"] for f in cleanup]
    sarif = json.loads((demo_reports / "report.sarif").read_text(encoding="utf-8"))
    nsg = next(r for r in sarif["runs"][0]["results"] if r["ruleId"] == "unattached_nsg")
    assert nsg["level"] == "note"


def test_summary_mentions_cleanup():
    fs = findings()
    text = render_summary(fs, summarize(fs, cleanup=3), RunInfo("x"))
    assert "3 kostenlos aufzuräumen" in text


def test_exports_without_cleanup_argument():
    data = json.loads(render_json(findings(), summarize(findings()), RunInfo("x")))
    assert data["cleanup"] == [] and data["summary"]["cleanup"] == 0
