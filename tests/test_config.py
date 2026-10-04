"""waste-finder.toml, CLI precedence, rule selection, exclusions and thresholds."""

import json

import pytest

from waste_finder.cli import main
from waste_finder.config import (
    ConfigError,
    Settings,
    is_ignored,
    load_config,
    resolve_settings,
    split_below_threshold,
    split_ignored,
)
from waste_finder.models import Finding
from waste_finder.registry import REGISTRY
from waste_finder.report import render

FULL_CONFIG = """
rules = ["stopped_vm", "orphaned_public_ip"]
exclude = ["*/resourceGroups/rg-test/*"]
currency = "chf"

[thresholds]
min_monthly_savings = 5
snapshot_min_age_days = 90
downgrade_lookback_days = 14
"""


def finding(resource_id="/subscriptions/s/resourceGroups/rg/providers/x/y", tags=None, cost=None):
    return Finding("stopped_vm", resource_id, "y", "rg", "we", "x", tags=tags or {}, monthly_cost_eur=cost)


@pytest.fixture
def config_file(tmp_path):
    def write(text):
        path = tmp_path / "waste-finder.toml"
        path.write_text(text, encoding="utf-8")
        return path

    return write


def test_defaults_without_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s = resolve_settings(None, {})
    assert s == Settings(rules=tuple(REGISTRY), exclude=(), min_monthly_savings=0.0, currency="EUR")
    assert (s.formats, s.fail_over, s.snapshot_min_age_days, s.downgrade_lookback_days) == (
        ("md", "html"),
        None,
        30,
        30,
    )
    assert s.min_age_days == {"old_snapshot": 30, "premium_disk_deallocated_vm": 30}
    assert s.source == "defaults"


def test_load_full_config(config_file):
    assert load_config(config_file(FULL_CONFIG)) == {
        "rules": ("stopped_vm", "orphaned_public_ip"),
        "exclude": ("*/resourceGroups/rg-test/*",),
        "currency": "CHF",
        "min_monthly_savings": 5.0,
        "snapshot_min_age_days": 90,
        "downgrade_lookback_days": 14,
    }


def test_file_in_working_directory_is_picked_up(config_file, monkeypatch):
    path = config_file('rules = ["stopped_vm"]')
    monkeypatch.chdir(path.parent)
    s = resolve_settings(None, {})
    assert s.rules == ("stopped_vm",) and s.source == "waste-finder.toml"


def test_cli_values_override_file_values(config_file):
    s = resolve_settings(
        config_file(FULL_CONFIG),
        {"rules": ("unattached_disk",), "exclude": None, "currency": None, "min_monthly_savings": 0.0},
    )
    assert s.rules == ("unattached_disk",)  # flag wins
    assert s.min_monthly_savings == 0.0  # an explicit 0 still overrides
    assert s.exclude == ("*/resourceGroups/rg-test/*",)  # no flag: file value
    assert s.currency == "CHF"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('rule = ["stopped_vm"]', "unknown key"),
        ('rules = ["nope"]', "unknown rule"),
        ("rules = []", "no rules selected"),
        ('rules = "stopped_vm"', "list of strings"),
        ("exclude = [1]", "list of strings"),
        ('currency = "XYZ"', "unsupported currency"),
        ("currency = 1", "currency must be a string"),
        ("[thresholds]\nmin_savings = 1", "supports only"),
        ("[thresholds]\nmin_monthly_savings = -1", ">= 0"),
        ("[thresholds]\nmin_monthly_savings = true", ">= 0"),
        ('formats = ["pdf"]', "unknown format"),
        ("formats = []", "no output format"),
        ("[thresholds]\nfail_over = -5", "fail_over must be"),
        ("[thresholds]\nsnapshot_min_age_days = -1", "snapshot_min_age_days must be"),
        ("[thresholds]\nsnapshot_min_age_days = 7.5", "whole number of days"),
        ("[thresholds]\nsnapshot_min_age_days = true", "whole number of days"),
        ("[thresholds]\ndowngrade_lookback_days = -3", "downgrade_lookback_days must be"),
        ('[thresholds]\ndowngrade_lookback_days = "30"', "whole number of days"),
        ("rules = [", "cannot read"),
    ],
)
def test_invalid_config_is_rejected(config_file, text, message):
    with pytest.raises(ConfigError, match=message):
        load_config(config_file(text))


def test_formats_and_fail_over_from_file_and_flags(config_file):
    path = config_file('formats = ["JSON", "csv", "json"]\n[thresholds]\nfail_over = 50')
    assert load_config(path) == {"formats": ("json", "csv"), "fail_over": 50.0}
    s = resolve_settings(path, {"formats": ("sarif",), "fail_over": None})
    assert (s.formats, s.fail_over) == (("sarif",), 50.0)


def test_missing_explicit_config_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(tmp_path / "missing.toml")


@pytest.mark.parametrize(
    "tags",
    [{"waste-finder:ignore": "true"}, {"Waste-Finder:Ignore": "True"}, {"waste-finder:ignore": " TRUE "}],
)
def test_ignore_tag(tags):
    assert is_ignored(finding(tags=tags))


@pytest.mark.parametrize("tags", [{}, {"waste-finder:ignore": "false"}, {"waste-finder:ignore": "yes"}])
def test_resources_without_ignore_tag_are_kept(tags):
    assert not is_ignored(finding(tags=tags))


def test_exclude_patterns_match_resource_id_case_insensitively():
    f = finding("/subscriptions/s/resourceGroups/RG-Sandbox/providers/Microsoft.Compute/disks/d1")
    assert is_ignored(f, ["*/resourcegroups/rg-sandbox/*"])
    assert not is_ignored(f, ["*/resourceGroups/rg-prod/*"])


def test_split_ignored_keeps_order():
    a, b, c = finding("a"), finding("b", tags={"waste-finder:ignore": "true"}), finding("c")
    assert split_ignored([a, b, c], ["c"]) == ([a], [b, c])


def test_threshold_keeps_unpriced_findings():
    cheap, dear, unpriced = finding(cost=1.0), finding(cost=10.0), finding(cost=None)
    assert split_below_threshold([cheap, dear, unpriced], 5.0) == ([dear, unpriced], [cheap])
    assert split_below_threshold([cheap], 0.0) == ([cheap], [])


def test_demo_counts_tagged_resource_as_ignored(tmp_path, capsys):
    assert main(["--demo", "--out-dir", str(tmp_path)]) == 0
    assert "1 ignored" in capsys.readouterr().out
    md = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "1 Ressource(n) ignoriert" in md and "pip-dns-reserved" not in md


def test_cli_rules_exclude_and_threshold(tmp_path, capsys):
    args = ["--demo", "--out-dir", str(tmp_path), "--rules", "stopped_vm, unattached_disk"]
    args += ["--exclude", "*/resourceGroups/rg-test/*", "--min-savings", "5"]
    assert main(args) == 0
    out = capsys.readouterr().out
    # stopped_vm: build-agent-02 excluded by pattern; unattached_disk: awf-orphaned-disk (1,41 €) below 5 €
    assert "2 findings" in out and "1 ignored" in out and "1 below the threshold of 5,00 €" in out
    md = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "awf-stopped-vm" in md and "erp-db-old-data" in md and "awf-orphaned-pip" not in md
    assert "unter der Schwelle von 5,00 €" in md


def test_cli_reads_config_file(config_file, tmp_path, capsys):
    path = config_file('rules = ["orphaned_public_ip"]\n[thresholds]\nmin_monthly_savings = 1')
    assert main(["--demo", "--config", str(path), "--out-dir", str(tmp_path / "out")]) == 0
    assert "2 findings" in capsys.readouterr().out


def test_demo_keeps_eur_prices(config_file, tmp_path, capsys):
    assert main(["--demo", "--config", str(config_file('currency = "USD"')), "--out-dir", str(tmp_path)]) == 0
    assert "ignoring currency USD" in capsys.readouterr().err
    assert "Listenpreise in EUR" in (tmp_path / "report.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "args",
    [
        ["--rules", "nope"],
        ["--currency", "XYZ"],
        ["--min-savings", "-1"],
        ["--config", "missing.toml"],
        ["--format", "md,pdf"],
        ["--fail-over", "-1"],
        ["--snapshot-min-age", "-1"],
        ["--downgrade-lookback", "-1"],
    ],
)
def test_cli_rejects_bad_settings(tmp_path, capsys, args):
    assert main(["--demo", "--out-dir", str(tmp_path), *args]) == 2
    assert "error:" in capsys.readouterr().err


@pytest.mark.parametrize("fmt", ["md", "html"])
def test_report_without_findings(fmt):
    text = render([], "sub", fmt, ignored=2)
    assert "Keine verschwendeten Ressourcen gefunden." in text
    assert "2 Ressource(n) ignoriert" in text


def test_report_groups_by_subscription_most_expensive_first():
    small = finding("/subscriptions/aaa/resourceGroups/rg/providers/x/small", cost=1.0)
    big = finding("/subscriptions/bbb/resourceGroups/rg/providers/x/big", cost=9.0)
    md = render([small, big], "aaa, bbb", "md")
    assert md.index("Subscription `bbb`") < md.index("Subscription `aaa`")
    assert "Ca. **9,00 € pro Monat** durch 1 Ressource(n)." in md


def test_snapshot_min_age_flag_overrides_file(config_file):
    path = config_file("[thresholds]\nsnapshot_min_age_days = 90")
    assert resolve_settings(path, {"snapshot_min_age_days": None}).snapshot_min_age_days == 90
    s = resolve_settings(path, {"snapshot_min_age_days": 0})
    assert s.snapshot_min_age_days == 0 and s.min_age_days["old_snapshot"] == 0


@pytest.mark.parametrize(
    ("flags", "count", "reported"),
    [
        ([], 3, False),  # default 30 days: erp-db-nightly (6 days) is too young
        (["--snapshot-min-age", "0"], 4, True),
        (["--snapshot-min-age", "100"], 2, False),  # awf-old-snapshot (45 days) drops out too
    ],
)
def test_cli_snapshot_min_age(tmp_path, capsys, flags, count, reported):
    assert main(["--demo", "--rules", "old_snapshot", "--out-dir", str(tmp_path), *flags]) == 0
    assert f"{count} findings" in capsys.readouterr().out
    md = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert ("erp-db-nightly" in md) == reported


def test_cli_snapshot_min_age_from_config(config_file, tmp_path, capsys):
    path = config_file('rules = ["old_snapshot"]\n[thresholds]\nsnapshot_min_age_days = 0')
    assert main(["--demo", "--config", str(path), "--out-dir", str(tmp_path / "out")]) == 0
    assert "4 findings" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("flags", "names"),
    [
        ([], ["sap-test-db-data", "web-old-vm-osdisk"]),  # jumpbox-osdisk: deallocated 3 days, under 30
        (["--downgrade-lookback", "0"], ["jumpbox-osdisk", "sap-test-db-data", "web-old-vm-osdisk"]),
        (["--downgrade-lookback", "60"], ["sap-test-db-data"]),
    ],
)
def test_cli_downgrade_lookback(tmp_path, flags, names):
    args = ["--demo", "--rules", "premium_disk_deallocated_vm", "--format", "json", "--out-dir", str(tmp_path)]
    assert main([*args, *flags]) == 0
    data = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert sorted(f["name"] for f in data["findings"]) == names


def test_downgrade_lookback_from_config_and_flag(config_file):
    path = config_file("[thresholds]\ndowngrade_lookback_days = 90")
    assert resolve_settings(path, {}).min_age_days["premium_disk_deallocated_vm"] == 90
    assert resolve_settings(path, {"downgrade_lookback_days": 7}).downgrade_lookback_days == 7
