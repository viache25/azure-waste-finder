"""Trend between runs: --previous <report.json>, the built-in previous demo run, report and export output."""

import csv
import io
import json
from pathlib import Path

import jsonschema
import pytest

from waste_finder import cli
from waste_finder.config import ConfigError
from waste_finder.demo import demo_fetcher, demo_previous_report, demo_runner
from waste_finder.models import Finding
from waste_finder.report import render, signed_eur, summarize
from waste_finder.trend import PreviousFinding, PreviousReport, compare, load_previous

SCHEMA = json.loads((Path(__file__).parent.parent / "docs" / "report.schema.json").read_text(encoding="utf-8"))
RG = "/subscriptions/s1/resourceGroups/rg/providers/Microsoft.Compute"


def now(rule, name, savings, resource_id=None):
    return Finding(rule, resource_id or f"{RG}/x/{name}", name, "rg", "we", "sku", monthly_cost_eur=savings)


def before(rule, name, savings, resource_id=None):
    return PreviousFinding(rule, resource_id or f"{RG}/x/{name}", name, "rg", "s1", savings)


def previous(*findings, scope="subscription s1", cost_source="retail"):
    return PreviousReport("2026-09-04", scope, "EUR", cost_source, tuple(findings))


def report_json(tmp_path, data, name="previous.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def minimal_report():
    return {
        "schema_version": "1.0",
        "tool": {"name": "azure-waste-finder", "version": "0.1.0"},
        "generated": "2026-09-01",
        "scope": "subscription s1",
        "currency": "EUR",
        "findings": [{"rule": "stopped_vm", "resource_id": f"{RG}/x/vm", "name": "vm", "monthly_savings": 8.18}],
    }


def test_load_a_1_0_report(tmp_path, minimal_report):
    minimal_report["findings"].append({"rule": "stopped_vm", "resource_id": "x", "name": "x", "monthly_savings": None})
    report = load_previous(report_json(tmp_path, minimal_report))
    assert (report.generated, report.scope, report.currency, report.cost_source) == (
        "2026-09-01",
        "subscription s1",
        "EUR",
        "retail",  # reports before 1.4 had no cost source: list prices
    )
    assert report.findings == (
        PreviousFinding("stopped_vm", f"{RG}/x/vm", "vm", "", "", 8.18),
        PreviousFinding("stopped_vm", "x", "x", "", "", None),  # unpriced
    )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d.update(tool={"name": "other"}), "not a report.json of azure-waste-finder"),
        (lambda d: d.update(tool="x"), "not a report.json"),
        (lambda d: d.update(schema_version="2.0"), "unsupported schema_version '2.0'"),
        (lambda d: d.pop("findings"), "missing or invalid field 'findings'"),
        (lambda d: d["findings"][0].pop("resource_id"), "missing or invalid field 'resource_id'"),
        (lambda d: d["findings"].append("vm"), "missing or invalid field"),
        (lambda d: d["findings"][0].update(monthly_savings="8"), "amounts must be numbers"),
        (lambda d: d["findings"][0].update(monthly_savings=True), "amounts must be numbers"),
    ],
)
def test_invalid_previous_report(tmp_path, minimal_report, change, message):
    change(minimal_report)
    with pytest.raises(ConfigError, match=message):
        load_previous(report_json(tmp_path, minimal_report))


def test_unreadable_previous_report(tmp_path):
    with pytest.raises(ConfigError, match="cannot read --previous"):
        load_previous(tmp_path / "missing.json")
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    with pytest.raises(ConfigError, match="cannot read --previous"):
        load_previous(tmp_path / "broken.json")
    (tmp_path / "list.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ConfigError, match=r"not a report\.json"):
        load_previous(tmp_path / "list.json")


def test_compare_new_resolved_unchanged():
    trend = compare(
        previous(
            before("stopped_vm", "vm", 100.0), before("unattached_disk", "gone", 5.0), before("stopped_vm", "same", 8.0)
        ),
        [now("stopped_vm", "vm", 120.0), now("stopped_vm", "same", 8.0), now("orphaned_public_ip", "ip", 3.36)],
        ["stopped_vm", "unattached_disk", "orphaned_public_ip"],
    )
    assert [f.name for f in trend.new] == ["ip"]
    assert [f.name for f in trend.resolved] == ["gone"]
    assert [f.name for f in trend.unchanged] == ["vm", "same"]
    assert [f.name for f in trend.changed] == ["vm"]
    assert (trend.previous_monthly, trend.current_monthly, trend.monthly_change) == (113.0, 131.36, 18.36)
    assert (trend.new_monthly, trend.resolved_monthly, trend.changed_monthly) == (3.36, 5.0, 20.0)
    assert trend.new_monthly - trend.resolved_monthly + trend.changed_monthly == pytest.approx(trend.monthly_change)
    assert [(r.status, r.name, r.previous, r.current) for r in trend.rows()] == [
        ("new", "ip", None, 3.36),
        ("resolved", "gone", 5.0, None),
        ("changed", "vm", 100.0, 120.0),
    ]


def test_same_resource_ignores_case_but_not_rule():
    trend = compare(
        previous(before("unattached_disk", "d", 5.0, resource_id=f"{RG}/disks/D1")),
        [now("unattached_disk", "d", 5.0, resource_id=f"{RG.lower()}/disks/d1")],
        ["unattached_disk", "premium_disk_deallocated_vm"],
    )
    assert (len(trend.new), len(trend.resolved), len(trend.unchanged)) == (0, 0, 1)
    # The same disk found by another rule counts as resolved + new.
    other = compare(
        previous(before("premium_disk_deallocated_vm", "d", 48.0, resource_id=f"{RG}/disks/d1")),
        [now("unattached_disk", "d", 67.0, resource_id=f"{RG}/disks/d1")],
        ["unattached_disk", "premium_disk_deallocated_vm"],
    )
    assert (len(other.new), len(other.resolved)) == (1, 1)


def test_only_rules_of_this_run_are_compared():
    trend = compare(
        previous(before("stopped_vm", "vm", 100.0), before("old_snapshot", "snap", 22.0)),
        [now("stopped_vm", "vm", 100.0)],
        ["stopped_vm"],  # --rules stopped_vm: the snapshot was not looked for, so it is not "resolved"
    )
    assert trend.resolved == () and trend.previous_monthly == 100.0 and trend.monthly_change == 0


def test_unpriced_findings_count_as_zero():
    trend = compare(previous(before("stopped_vm", "vm", None)), [now("stopped_vm", "vm", None)], ["stopped_vm"])
    assert (trend.previous_monthly, trend.monthly_change, trend.changed) == (0.0, 0.0, ())
    assert trend.previous_amount(trend.unchanged[0]) is None and trend.status(trend.unchanged[0]) == "unchanged"


@pytest.mark.parametrize(
    ("value", "currency", "text"),
    [
        (28.913, "EUR", "+28,91 €"),
        (-9.97, "EUR", "-9,97 €"),
        (0.001, "EUR", "0,00 €"),
        (-1234.5, "CHF", "-1.234,50 CHF"),
    ],
)
def test_signed_amount(value, currency, text):
    assert signed_eur(value, currency) == text


def test_demo_previous_report_is_a_valid_older_report():
    path = Path(cli.__file__).parent / "demo" / "previous-report.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    jsonschema.validate(data, SCHEMA, format_checker=jsonschema.FormatChecker())
    assert data["schema_version"] == "1.3" and data["summary"]["monthly_savings"] == 519.0
    report = demo_previous_report()
    assert len(report.findings) == 15 and report.generated == "2026-09-04"


@pytest.fixture
def demo_trend(tmp_path, capsys):
    args = ["--demo", "--format", "md,html,json,csv", "--out-dir", str(tmp_path), "--summary", str(tmp_path / "s.md")]
    assert cli.main(args) == 0
    return tmp_path, capsys.readouterr().out


def test_demo_report_shows_a_trend(demo_trend):
    out_dir, out = demo_trend
    assert "trend since 2026-09-04: -9,97 € per month (2 new, 2 resolved, 13 unchanged)" in out
    md = (out_dir / "report.md").read_text(encoding="utf-8")
    trend = md[md.index("## Entwicklung seit dem letzten Bericht") : md.index("## Gefundene Ressourcen")]
    assert (
        "Letzter Bericht vom 2026-09-04: ca. 519,00 € pro Monat. Jetzt ca. 509,03 €, also **-9,97 € pro Monat**."
        in trend
    )
    assert "2 neu (+77,34 €), 2 behoben (-151,55 €), 13 unverändert, davon 1 mit geändertem Betrag (+64,24 €)." in trend
    assert "| neu | `sap-test-db-data` | Premium-Disk an deallozierter VM |" in trend
    assert "| behoben | `build-agent-01` | VM gestoppt, aber nicht dealloziert |" in trend
    assert "| 148,19 € | \u2013 |" in trend and "| geändert | `asp-intranet-legacy` |" in trend
    assert "| 64,24 € | 128,48 € |" in trend
    assert "Kostenquelle" not in trend and "Bereich `" not in trend  # same source and scope as before
    html = (out_dir / "report.html").read_text(encoding="utf-8")
    assert '<h2 id="entwicklung">Entwicklung seit dem letzten Bericht</h2>' in html
    assert '<span class="trend trend-resolved">behoben</span>' in html and "<code>pip-old-vpn</code>" in html
    summary = (out_dir / "s.md").read_text(encoding="utf-8")
    assert "Seit dem letzten Bericht (2026-09-04): **-9,97 € pro Monat**; 2 neu, 2 behoben, 13 unverändert." in summary


def test_demo_trend_in_json_and_csv(demo_trend):
    out_dir, _ = demo_trend
    data = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    jsonschema.validate(data, SCHEMA, format_checker=jsonschema.FormatChecker())
    trend = data["trend"]
    assert trend["previous"] == {
        "generated": "2026-09-04",
        "scope": "demo (Contoso)",
        "cost_source": "retail",
        "monthly_savings": 519.0,
    }
    assert (trend["monthly_savings_change"], trend["new"], trend["resolved"], trend["unchanged"], trend["changed"]) == (
        -9.97,
        2,
        2,
        13,
        1,
    )
    assert [f["name"] for f in trend["resolved_findings"]] == ["build-agent-01", "pip-old-vpn"]
    by_name = {f["name"]: f for f in data["findings"]}
    assert (by_name["natgw-old-hub"]["trend"], by_name["natgw-old-hub"]["previous_monthly_savings"]) == ("new", None)
    assert (by_name["asp-intranet-legacy"]["trend"], by_name["asp-intranet-legacy"]["previous_monthly_savings"]) == (
        "unchanged",
        64.24,
    )
    assert all(f["trend"] is None for f in data["cleanup"])
    rows = {r["name"]: r for r in csv.DictReader(io.StringIO((out_dir / "report.csv").read_text("utf-8")))}
    assert rows["natgw-old-hub"]["trend"] == "new" and rows["erp-db-old-data"]["trend"] == "unchanged"
    assert rows["web-old-nsg"]["trend"] == ""


def test_demo_without_trend(tmp_path, capsys):
    assert cli.main(["--demo", "--previous", "", "--format", "md,html,json", "--out-dir", str(tmp_path)]) == 0
    assert "trend since" not in capsys.readouterr().out
    assert "Entwicklung" not in (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "Entwicklung" not in (tmp_path / "report.html").read_text(encoding="utf-8")
    data = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert data["trend"] is None and {f["trend"] for f in data["findings"]} == {None}


def test_previous_run_of_the_same_findings_shows_no_change(tmp_path, capsys):
    assert cli.main(["--demo", "--previous", "", "--format", "json", "--out-dir", str(tmp_path / "1")]) == 0
    args = ["--demo", "--previous", str(tmp_path / "1" / "report.json"), "--out-dir", str(tmp_path / "2")]
    assert cli.main(args) == 0
    assert "+0,00 €" not in capsys.readouterr().out
    for fmt in ("md", "html"):
        text = (tmp_path / "2" / f"report.{fmt}").read_text(encoding="utf-8")
        assert "Keine Veränderung seit dem letzten Bericht." in text and "0 neu (0,00 €)" in text


def test_previous_report_with_other_scope_and_cost_source(tmp_path, capsys):
    assert cli.main(["--demo", "--cost-source", "actual", "--format", "json", "--out-dir", str(tmp_path / "1")]) == 0
    data = json.loads((tmp_path / "1" / "report.json").read_text(encoding="utf-8"))
    data["scope"] = "subscription old"
    path = report_json(tmp_path, data)
    assert cli.main(["--demo", "--previous", str(path), "--out-dir", str(tmp_path / "2")]) == 0
    md = (tmp_path / "2" / "report.md").read_text(encoding="utf-8")
    assert "Letzter Bericht vom " in md and "(Bereich `subscription old`)" in md
    assert "Der letzte Bericht nutzte Ist-Kosten; ein Teil der Änderung kann von der anderen Kostenquelle kommen." in md
    html = (tmp_path / "2" / "report.html").read_text(encoding="utf-8")
    assert "(Bereich <code>subscription old</code>)" in html and "Der letzte Bericht nutzte Ist-Kosten" in html


def test_report_mentions_list_prices_when_the_previous_run_used_them():
    f = now("stopped_vm", "vm", 1.0)
    trend = compare(previous(before("stopped_vm", "vm", 1.0)), [f], ["stopped_vm"])
    md = render([f], "subscription s1", "md", trend=trend, cost_source="actual")
    assert "Der letzte Bericht nutzte Listenpreise" in md


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--previous", "missing.json"], "cannot read --previous missing.json"),
        (["--previous", "chf.json"], "--previous chf.json is in CHF, this run in EUR; amounts cannot be compared"),
    ],
)
def test_cli_rejects_unusable_previous_reports(tmp_path, monkeypatch, capsys, minimal_report, args, message):
    monkeypatch.chdir(tmp_path)
    report_json(tmp_path, {**minimal_report, "currency": "CHF"}, "chf.json")
    assert cli.main(["--demo", "--out-dir", "out", *args]) == 2
    assert message in capsys.readouterr().err


def test_real_run_with_previous_report(monkeypatch, tmp_path, capsys, minimal_report):
    monkeypatch.setattr(cli, "resource_graph_runner", lambda scope: demo_runner())
    monkeypatch.setattr(cli, "retail_api_fetcher", lambda cache_file, currency: demo_fetcher())
    path = report_json(tmp_path, minimal_report)  # one stopped VM that is gone now
    args = ["--subscription", "s1", "--rules", "stopped_vm", "--previous", str(path), "--out-dir", str(tmp_path / "o")]
    assert cli.main(args) == 0
    assert "trend since 2026-09-01: +148,19 € per month (2 new, 1 resolved, 0 unchanged)" in capsys.readouterr().out


def test_report_without_trend_is_unchanged():
    f = now("stopped_vm", "vm", 1.0)
    assert render([f], "s", "md") == render([f], "s", "md", trend=None)
    assert summarize([f]).monthly_eur == 1.0
