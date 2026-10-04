from waste_finder.cli import main
from waste_finder.models import Finding
from waste_finder.report import eur, render, summarize


def test_eur_format():
    assert eur(1234.5) == "1.234,50 €"
    assert eur(None) == "n/a"


def test_summary_skips_unpriced():
    fs = [
        Finding("stopped_vm", "a", "a", "rg", "we", "x", monthly_cost_eur=10.0),
        Finding("stopped_vm", "b", "b", "rg", "we", "x", monthly_cost_eur=None),
    ]
    s = summarize(fs)
    assert (s.count, s.monthly_eur, s.yearly_eur, s.unpriced) == (2, 10.0, 120.0, 1)


def test_html_escapes_resource_names():
    f = Finding("stopped_vm", "a", "<script>", "rg", "we", "x", monthly_cost_eur=1.0)
    assert "<script>" not in render([f], "sub", "html")


def test_demo_run_writes_both_reports(tmp_path, capsys):
    assert main(["--demo", "--out-dir", str(tmp_path)]) == 0
    md = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "pro Monat" in md and "Demo-Daten" in md
    assert (tmp_path / "report.html").exists()
    assert "9 findings" in capsys.readouterr().out


def test_real_run_needs_subscription(monkeypatch):
    monkeypatch.delenv("AZURE_SUBSCRIPTION_ID", raising=False)
    assert main([]) == 2


def test_summary_total_is_savings_not_cost():
    fs = [
        Finding("stopped_vm", "a", "a", "rg", "we", "x", monthly_cost_eur=10.0),
        Finding("unattached_disk", "b", "b", "rg", "we", "x", monthly_cost_eur=50.0, monthly_savings_eur=20.0),
    ]
    s = summarize(fs)
    assert (s.monthly_eur, s.unpriced) == (30.0, 0)


def test_savings_default_to_full_cost():
    f = Finding("stopped_vm", "a", "a", "rg", "we", "x", monthly_cost_eur=10.0)
    assert f.savings_eur == 10.0
    f.monthly_savings_eur = 4.0
    assert f.savings_eur == 4.0
    assert Finding("stopped_vm", "a", "a", "rg", "we", "x").savings_eur is None


def test_report_shows_severity_docs_and_command(tmp_path):
    assert main(["--demo", "--out-dir", str(tmp_path)]) == 0
    for fmt in ("md", "html"):
        text = (tmp_path / f"report.{fmt}").read_text(encoding="utf-8")
        assert "Priorität" in text and "hoch" in text
        assert "az vm deallocate --ids /subscriptions/" in text
        assert "https://learn.microsoft.com/azure/virtual-machines/states-billing" in text
