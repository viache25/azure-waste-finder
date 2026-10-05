import pytest

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
    f = Finding("stopped_vm", "a", "<script>alert(1)</script>", "rg", "we", "x", monthly_cost_eur=1.0)
    html = render([f], "sub", "html")
    assert "<script>alert(1)" not in html and "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert html.count("<script>") == 1  # only the report's own table sorting


def test_demo_run_writes_both_reports(tmp_path, capsys):
    assert main(["--demo", "--out-dir", str(tmp_path)]) == 0
    md = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "pro Monat" in md and "Demo-Daten" in md
    assert (tmp_path / "report.html").exists()
    assert "15 findings" in capsys.readouterr().out


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


def test_report_shows_cost_and_savings_separately(tmp_path):
    assert main(["--demo", "--out-dir", str(tmp_path)]) == 0
    md = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "| Kosten €/Monat | Einsparung €/Monat |" in md
    assert "| Premium_LRS (512 GB), 75 Tage dealloziert | 67,58 € | 48,43 € |" in md
    assert "Die Ressourcen kosten zusammen ca. 533,36 € pro Monat" in md
    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "Einsparung €/Monat" in html and '<td class="num">48,43 €</td>' in html


def test_cost_note_only_when_cost_and_savings_differ():
    f = Finding("stopped_vm", "a", "a", "rg", "we", "x", monthly_cost_eur=10.0)
    assert "kosten zusammen" not in render([f], "sub", "md")
    s = summarize(
        [f, Finding("unattached_disk", "b", "b", "rg", "we", "x", monthly_cost_eur=50.0, monthly_savings_eur=20.0)]
    )
    assert (s.monthly_cost_eur, s.monthly_eur) == (60.0, 30.0)


def test_report_has_free_cleanup_section_outside_the_total(tmp_path, capsys):
    assert main(["--demo", "--out-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "6 free clean-up finding(s), not in the total:" in out and "free  info" in out
    md = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "## Aufräumen (kostenlos)" in md and "Dazu 6 kostenlose Ressource(n) zum Aufräumen" in md
    cleanup = md[md.index("## Aufräumen (kostenlos)") : md.index("## Warum kostet das Geld?")]
    for name in ("awf-idle-lb", "web-old-nsg", "build-agent-01-nic", "rg-poc-2024"):
        assert f"`{name}`" in cleanup
    assert "az group delete --name rg-poc-2024 --subscription 11111111-1111-1111-1111-111111111111" in cleanup
    assert "`web-old-nsg`" not in md[: md.index("## Aufräumen (kostenlos)")]  # not among the paid findings
    why = md[md.index("## Warum kostet das Geld?") :]
    assert "Leere Ressourcengruppe" not in why  # free rules explain themselves in the clean-up section
    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert '<h2 id="aufraeumen">Aufräumen (kostenlos)</h2>' in html and "<code>rg-migration-temp</code>" in html


def test_cleanup_is_not_dropped_by_the_savings_threshold(tmp_path, capsys):
    assert main(["--demo", "--out-dir", str(tmp_path), "--min-savings", "5"]) == 0
    out = capsys.readouterr().out
    assert "6 free clean-up finding(s)" in out
    # Below 5 €: two public IPs (3,36), web-old-vm-osdisk (3,27), awf-orphaned-disk and awf-old-snapshot (1,41).
    assert "10 findings" in out and "5 below the threshold" in out


@pytest.mark.parametrize("fmt", ["md", "html"])
def test_no_cleanup_section_without_free_findings(fmt):
    f = Finding("stopped_vm", "a", "a", "rg", "we", "x", monthly_cost_eur=1.0)
    assert "Aufräumen (kostenlos)" not in render([f], "sub", fmt)
