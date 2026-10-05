"""HTML report: bar chart per rule, severity badges, sortable tables, print and dark mode, no external resources."""

import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

import pytest

from waste_finder.cli import main
from waste_finder.models import Finding
from waste_finder.registry import REGISTRY, SEVERITIES
from waste_finder.report import CHART_MAX_PERCENT, SEVERITY_RANK, render, rule_chart, severity_counts


def finding(rule, name, cost, savings=None, severity=None):
    return Finding(
        rule,
        f"/subscriptions/s/resourceGroups/rg/providers/x/{name}",
        name,
        "rg",
        "westeurope",
        "sku",
        monthly_cost_eur=cost,
        monthly_savings_eur=savings,
        severity=severity or REGISTRY[rule].severity,
    )


class Elements(HTMLParser):
    """Every start tag with its attributes, and the text of each <script> (tag names come lower-cased)."""

    def __init__(self, html):
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.scripts: list[str] = []
        self._in_script = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        if tag == "script":
            self._in_script = True
            self.scripts.append("")

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_script = False

    def handle_data(self, data):
        if self._in_script:
            self.scripts[-1] += data


@pytest.fixture(scope="module")
def demo_html(tmp_path_factory):
    out = tmp_path_factory.mktemp("html")
    assert main(["--demo", "--format", "html", "--out-dir", str(out)]) == 0
    return (out / "report.html").read_text(encoding="utf-8")


def test_rule_chart_sums_savings_per_rule_largest_first():
    findings = [
        finding("unattached_disk", "d1", 10.0),
        finding("stopped_vm", "vm1", 100.0),
        finding("unattached_disk", "d2", 15.0),
        finding("premium_disk_deallocated_vm", "p1", 60.0, savings=40.0),  # savings, not cost
        finding("orphaned_public_ip", "ip1", None),  # unpriced: counted, adds nothing
    ]
    bars = rule_chart(findings)
    assert [(b.rule, b.count, b.monthly_eur) for b in bars] == [
        ("stopped_vm", 1, 100.0),
        ("premium_disk_deallocated_vm", 1, 40.0),
        ("unattached_disk", 2, 25.0),
    ]
    assert [b.percent for b in bars] == [CHART_MAX_PERCENT, 30.0, 18.75]
    assert bars[0].label == REGISTRY["stopped_vm"].title_de


def test_rule_chart_ties_follow_the_registry_order():
    bars = rule_chart([finding("orphaned_public_ip", "ip", 5.0), finding("unattached_disk", "d", 5.0)])
    assert [b.rule for b in bars] == ["unattached_disk", "orphaned_public_ip"]
    assert {b.percent for b in bars} == {CHART_MAX_PERCENT}


def test_rule_chart_needs_two_rules_with_savings():
    assert rule_chart([]) == []
    assert rule_chart([finding("stopped_vm", "a", 10.0), finding("stopped_vm", "b", 20.0)]) == []
    assert rule_chart([finding("stopped_vm", "a", 10.0), finding("unattached_disk", "d", None)]) == []
    assert rule_chart([finding("stopped_vm", "a", 10.0), finding("idle_load_balancer", "lb", 0.0)]) == []


def test_severity_counts_in_report_order():
    findings = [
        finding("orphaned_public_ip", "ip", 3.0),
        finding("stopped_vm", "vm", 9.0),
        finding("unattached_disk", "d", 1.0),
        finding("orphaned_public_ip", "ip2", 3.0),
    ]
    assert list(severity_counts(findings).items()) == [("high", 1), ("medium", 1), ("low", 2)]
    assert severity_counts([]) == {}
    assert list(SEVERITY_RANK) == list(reversed(SEVERITIES)) and SEVERITY_RANK["high"] > SEVERITY_RANK["info"]


def test_demo_chart_is_inline_svg(demo_html):
    assert '<h2 id="nach-problem">Einsparpotenzial nach Problem</h2>' in demo_html
    svg = demo_html[demo_html.index("<svg") : demo_html.index("</svg>")]
    assert 'role="img"' in svg and 'aria-labelledby="chart-title chart-desc"' in svg
    assert svg.count('<rect class="bar"') == 2 * 8  # 8 rules with savings in the demo; bar + square baseline end
    assert '<rect class="bar" y="22" width="75.0%" height="14" rx="4"></rect>' in svg  # the largest bar
    assert "<title>VM gestoppt, aber nicht dealloziert: 156,37 € pro Monat, 2 Ressource(n)</title>" in svg
    assert 'dx="8" y="33.5">156,37 €</text>' in svg
    assert "VM gestoppt, aber nicht dealloziert: 156,37 € (2 Ressource(n)); Leerer App-Service-Plan" in svg
    assert 'height="352"' in svg  # 8 rows of 44 px
    for rule in REGISTRY.values():
        if rule.pricing == "free":
            assert rule.title_de not in svg
    assert "zusammen ca. 509,03 €." in demo_html


def test_no_chart_for_a_single_rule():
    html = render([finding("stopped_vm", "vm", 10.0)], "sub", "html")
    assert "<svg" not in html and "Einsparpotenzial" not in html
    assert "Nach Priorität: " in html


def test_severity_badges(demo_html):
    assert (
        'Nach Priorität: <span class="sev sev-high">hoch</span> 2 · <span class="sev sev-medium">mittel</span> 7 · '
        '<span class="sev sev-low">niedrig</span> 6</div>'
    ) in demo_html
    assert '<td data-sort="3"><span class="sev sev-high">hoch</span></td>' in demo_html
    assert '<td data-sort="1"><span class="sev sev-low">niedrig</span></td>' in demo_html
    for severity in SEVERITIES:
        assert f".sev-{severity} {{ color: var(--sev-{severity}-fg); background: var(--sev-{severity}-bg); }}" in (
            demo_html
        )


def test_tables_are_sortable_without_needing_javascript(demo_html):
    # trend table, two subscriptions, clean-up section
    assert demo_html.count('<table class="sortable">') == 4
    assert demo_html.count('<th class="num" aria-sort="descending">Einsparung €/Monat</th>') == 2
    assert demo_html.count('<th class="nosort">Empfehlung</th>') == 3
    script = Elements(demo_html).scripts
    assert len(script) == 1
    assert 'querySelectorAll("table.sortable")' in script[0] and 'setAttribute("aria-sort"' in script[0]
    assert 'localeCompare(y, "de")' in script[0]
    # Without JavaScript the rows are already in report order: most savings first.
    first_table = demo_html[demo_html.index("<h2>Subscription") :]
    amounts = re.findall(r'<td class="num">([\d.,]+) €</td>', first_table[: first_table.index("</table>")])
    savings = [float(a.replace(".", "").replace(",", ".")) for a in amounts[1::2]]
    assert savings == sorted(savings, reverse=True)


def test_report_is_self_contained(demo_html):
    """No CDN, no web fonts, no external scripts or stylesheets: the file works offline and in an e-mail."""
    assert "@import" not in demo_html and "url(" not in demo_html
    tags = Elements(demo_html).tags
    assert not [tag for tag, _ in tags if tag in {"link", "img", "iframe", "object", "embed"}]
    assert not [tag for tag, attrs in tags if "src" in attrs]
    links = {urlsplit(attrs["href"] or "")[:2] for _, attrs in tags if "href" in attrs}
    assert links == {("https", "learn.microsoft.com")}  # only the docs links


def test_dark_mode_and_print_styles(demo_html):
    assert '<meta name="color-scheme" content="light dark">' in demo_html
    assert "@media (prefers-color-scheme: dark)" in demo_html
    print_css = demo_html[demo_html.index("@media print") :]
    assert "color-scheme: light;" in print_css and "--bg:#fff;" in print_css  # light colors on paper, also in dark mode
    assert "print-color-adjust: exact" in print_css and "thead { display: table-header-group; }" in print_css
    assert "th .sort::after { content: none; }" in print_css
    assert demo_html.index("@media (prefers-color-scheme: dark)") < demo_html.index("@media print")
    assert '<ul class="why">' in demo_html and '.why a::after { content: " (" attr(href) ")";' in print_css


def test_markdown_report_has_no_html_extras(tmp_path):
    assert main(["--demo", "--format", "md", "--out-dir", str(tmp_path)]) == 0
    md = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "<svg" not in md and "<script" not in md and "Einsparpotenzial" not in md
