"""Actual costs from Cost Management (--cost-source actual), tested with recorded-format API responses."""

import csv
import io
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest
import requests

from waste_finder import cli, costs
from waste_finder.costs import (
    ActualCost,
    CostManagementError,
    CostPeriod,
    apply_actual_costs,
    collect_actual_costs,
    cost_management_query,
    last_days,
    parse_query_result,
    query_body,
)
from waste_finder.demo import demo_cost_query, demo_fetcher, demo_runner
from waste_finder.models import Finding

FIXTURES = Path(__file__).parent / "fixtures" / "cost_management"
SCHEMA = json.loads((Path(__file__).parent.parent / "docs" / "report.schema.json").read_text(encoding="utf-8"))
SUB = "22222222-2222-2222-2222-222222222222"
RG = f"/subscriptions/{SUB}/resourceGroups/rg-test/providers"
PERIOD = CostPeriod(date(2026, 9, 4), date(2026, 10, 3))


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_last_30_full_days_end_yesterday():
    period = last_days(date(2026, 10, 4))
    assert period == PERIOD and (period.end - period.start).days == 29
    assert period.label() == "04.09.2026 bis 03.10.2026"


def test_query_body_asks_for_amortized_cost_per_resource():
    body = query_body(PERIOD)
    assert body["type"] == "AmortizedCost" and body["timeframe"] == "Custom"
    assert body["timePeriod"] == {"from": "2026-09-04T00:00:00Z", "to": "2026-10-03T23:59:59Z"}
    assert body["dataset"]["granularity"] == "None"
    assert body["dataset"]["aggregation"] == {"totalCost": {"name": "Cost", "function": "Sum"}}
    assert body["dataset"]["grouping"] == [{"type": "Dimension", "name": "ResourceId"}]


def test_parse_rows_by_lower_case_resource_id():
    result = parse_query_result(fixture("query_page1.json"))
    assert set(result) == {
        f"{RG}/microsoft.compute/virtualmachines/vm-build".lower(),
        f"{RG}/microsoft.compute/disks/disk-old".lower(),
        f"{RG}/microsoft.network/loadbalancers/lb-empty".lower(),
    }  # the row without a resource ID (e.g. a marketplace fee) is skipped
    assert result[f"{RG}/microsoft.compute/disks/disk-old".lower()] == ActualCost(1.3632, "EUR")


def test_parse_pre_tax_cost_column_and_other_currency():
    [(resource_id, cost)] = parse_query_result(fixture("query_pretaxcost_usd.json")).items()
    assert resource_id.endswith("/virtualmachines/vm-x") and cost == ActualCost(9.4608, "USD")


def test_parse_sums_duplicate_rows():
    body = fixture("query_page1.json")
    body["properties"]["rows"] += [[1.0, body["properties"]["rows"][0][1], "EUR"]]
    vm = parse_query_result(body)[f"{RG}/microsoft.compute/virtualmachines/vm-build".lower()]
    assert vm.amount == pytest.approx(142.3790272)


@pytest.mark.parametrize(
    "body",
    [{}, {"properties": {"columns": [{"name": "Other"}], "rows": []}}, {"properties": None}],
)
def test_unexpected_response_is_an_error(body):
    with pytest.raises(CostManagementError, match="unexpected Cost Management response"):
        parse_query_result(body)


class FakeResponse:
    def __init__(self, status, body=None, headers=None, reason="", text_only=False):
        self.status_code, self.body, self.headers, self.reason, self.text_only = (
            status,
            body,
            headers or {},
            reason,
            text_only,
        )

    def json(self):
        if self.text_only:
            raise ValueError("no JSON")
        return self.body


class FakeCredential:
    def __init__(self):
        self.scopes = []

    def get_token(self, *scopes):
        self.scopes.append(scopes)
        return SimpleNamespace(token="tok")


@pytest.fixture
def fake_post(monkeypatch):
    """Answers POSTs from a queue of responses and records (url, json, headers)."""
    calls, responses = [], []

    def post(url, json=None, headers=None, timeout=None):
        calls.append((url, json, headers))
        return responses.pop(0)

    monkeypatch.setattr(costs.requests, "post", post)
    return SimpleNamespace(calls=calls, responses=responses)


def test_query_follows_next_link_with_same_body(fake_post):
    fake_post.responses += [
        FakeResponse(200, fixture("query_page1.json")),
        FakeResponse(200, fixture("query_page2.json")),
    ]
    credential = FakeCredential()
    result = cost_management_query(PERIOD, credential=credential)(SUB)
    (url1, body1, headers1), (url2, body2, _) = fake_post.calls
    assert url1 == (
        f"https://management.azure.com/subscriptions/{SUB}/providers/Microsoft.CostManagement/query"
        "?api-version=2023-11-01"
    )
    assert url2 == fixture("query_page1.json")["properties"]["nextLink"]
    assert body1 == body2 == query_body(PERIOD)
    assert headers1 == {"Authorization": "Bearer tok"}
    assert credential.scopes[0] == ("https://management.azure.com/.default",)
    assert len(result) == 4
    disk = result[f"{RG}/microsoft.compute/disks/disk-old".lower()]
    assert disk.amount == pytest.approx(1.3632 + 0.0187)  # rows of one resource on two pages are added up


def test_query_retries_when_throttled(fake_post):
    sleeps = []
    fake_post.responses += [
        FakeResponse(429, fixture("error_429.json"), {"x-ms-ratelimit-microsoft.costmanagement-qpu-retry-after": "7"}),
        FakeResponse(429, fixture("error_429.json"), {"Retry-After": "600"}),
        FakeResponse(429, fixture("error_429.json")),
        FakeResponse(200, fixture("query_page2.json")),
    ]
    result = cost_management_query(PERIOD, credential=FakeCredential(), sleep=sleeps.append)(SUB)
    assert sleeps == [7.0, 60.0, 5.0]  # header value, capped at 60 s, default 5 s
    assert len(result) == 2


def test_query_gives_up_after_retries(fake_post):
    fake_post.responses += [FakeResponse(429, fixture("error_429.json")) for _ in range(4)]
    with pytest.raises(CostManagementError, match="HTTP 429: Too many requests"):
        cost_management_query(PERIOD, credential=FakeCredential(), sleep=lambda s: None)(SUB)


def test_forbidden_names_the_required_role(fake_post):
    fake_post.responses.append(FakeResponse(403, fixture("error_403.json")))
    with pytest.raises(CostManagementError) as error:
        cost_management_query(PERIOD, credential=FakeCredential())(SUB)
    assert "HTTP 403: The client does not have authorization" in str(error.value)
    assert "Cost Management Reader" in str(error.value)


def test_error_without_json_body_uses_the_reason(fake_post):
    fake_post.responses.append(FakeResponse(500, reason="Internal Server Error", text_only=True))
    with pytest.raises(CostManagementError, match=r"HTTP 500: Internal Server Error$"):
        cost_management_query(PERIOD, credential=FakeCredential())(SUB)


def test_default_credential_is_default_azure_credential(monkeypatch, fake_post):
    import azure.identity

    monkeypatch.setattr(azure.identity, "DefaultAzureCredential", FakeCredential)
    fake_post.responses.append(FakeResponse(200, fixture("query_page2.json")))
    assert len(cost_management_query(PERIOD)(SUB)) == 2


def test_collect_queries_each_subscription_once_and_survives_failures():
    asked, warnings = [], []

    def query(subscription_id):
        asked.append(subscription_id)
        if subscription_id == "bad":
            raise CostManagementError("HTTP 403: denied")
        if subscription_id == "offline":
            raise requests.ConnectionError("no route")
        return {f"/subscriptions/{subscription_id}/x": ActualCost(1.0, "EUR")}

    result = collect_actual_costs(query, ["s2", "bad", "s1", "s2", "offline"], warnings.append)
    assert asked == ["bad", "offline", "s1", "s2"]
    assert set(result) == {"/subscriptions/s1/x", "/subscriptions/s2/x"}
    assert len(warnings) == 2 and "subscription bad failed, using retail prices: HTTP 403" in warnings[0]


def priced(rule, name, cost, savings=None, severity="medium", note="1 €/h × 730 h"):
    return Finding(
        rule,
        f"{RG}/x/{name}",
        name,
        "rg-test",
        "westeurope",
        "sku",
        severity=severity,
        monthly_cost_eur=cost,
        monthly_savings_eur=savings,
        price_note=note,
        cost_source="retail" if cost is not None else None,
    )


def actual(*pairs, currency="EUR"):
    return {f"{RG}/x/{name}".lower(): ActualCost(amount, currency) for name, amount in pairs}


def test_actual_cost_replaces_retail_price():
    f = priced("stopped_vm", "vm", 148.19, severity="high")
    result = apply_actual_costs([f], actual(("vm", 139.8249)), "EUR", PERIOD)
    assert result == costs.ApplyResult(actual=1, other_currency=0)
    assert (f.monthly_cost_eur, f.savings_eur, f.cost_source, f.severity) == (139.82, 139.82, "actual", "high")
    assert f.price_note == "actual: amortized cost 2026-09-04 to 2026-10-03 (Cost Management); retail: 1 €/h × 730 h"


def test_findings_without_cost_row_keep_retail():
    f = priced("orphaned_public_ip", "pip", 3.36, severity="low")
    assert apply_actual_costs([f], actual(("other", 1.0)), "EUR", PERIOD).actual == 0
    assert (f.monthly_cost_eur, f.cost_source) == (3.36, "retail")


def test_cost_rows_in_another_currency_are_not_used():
    f = priced("stopped_vm", "vm", 148.19)
    result = apply_actual_costs([f], actual(("vm", 160.0), currency="USD"), "EUR", PERIOD)
    assert result == costs.ApplyResult(actual=0, other_currency=1)
    assert (f.monthly_cost_eur, f.cost_source) == (148.19, "retail")


def test_unpriced_finding_gets_its_actual_cost():
    f = priced("stopped_vm", "vm", None, note="no VM price found")
    apply_actual_costs([f], actual(("vm", 50.0)), "EUR", PERIOD)
    assert (f.monthly_cost_eur, f.cost_source) == (50.0, "actual")
    assert f.price_note.endswith("; retail: no VM price found")


def test_downgrade_keeps_the_retail_ratio_of_savings_to_cost():
    f = priced("premium_disk_deallocated_vm", "disk", 67.58, savings=48.43)
    apply_actual_costs([f], actual(("disk", 66.65)), "EUR", PERIOD)
    assert (f.monthly_cost_eur, f.monthly_savings_eur) == (66.65, round(66.65 * 48.43 / 67.58, 2))


def test_downgrade_without_retail_savings_stays_unpriced():
    f = priced("premium_disk_deallocated_vm", "disk", None, note="no price for S20 LRS to compare with")
    assert apply_actual_costs([f], actual(("disk", 66.65)), "EUR", PERIOD).actual == 0
    assert f.monthly_cost_eur is None and f.cost_source is None


def test_downgrade_with_free_retail_cost_saves_nothing():
    f = priced("premium_disk_deallocated_vm", "disk", 0.0, savings=0.0, severity="info")
    apply_actual_costs([f], actual(("disk", 2.0)), "EUR", PERIOD)
    assert (f.monthly_cost_eur, f.monthly_savings_eur, f.severity) == (2.0, 0.0, "info")


def test_severity_follows_the_actual_cost():
    free_lb = priced("idle_load_balancer", "lb", 0.0, severity="info")
    idle_ip = priced("orphaned_public_ip", "pip", 3.36, severity="low")
    apply_actual_costs([free_lb, idle_ip], actual(("lb", 4.2), ("pip", 0.0)), "EUR", PERIOD)
    assert (free_lb.monthly_cost_eur, free_lb.severity) == (4.2, "low")  # billed after all: rule severity
    assert (idle_ip.monthly_cost_eur, idle_ip.severity, idle_ip.is_free) == (0.0, "info", True)


def test_demo_cost_query_knows_both_demo_subscriptions():
    query = demo_cost_query()
    assert len(query("11111111-1111-1111-1111-111111111111")) == 7
    assert query("unknown") == {}


@pytest.fixture
def actual_reports(tmp_path, capsys):
    args = ["--demo", "--cost-source", "actual", "--format", "md,html,json,csv,sarif", "--out-dir", str(tmp_path)]
    args += ["--summary", str(tmp_path / "summary.md")]
    assert cli.main(args) == 0
    return tmp_path, capsys.readouterr().out


def test_demo_with_actual_costs(actual_reports):
    out_dir, out = actual_reports
    assert "15 findings, ~457,62 € per month" in out
    assert "10 priced from Cost Management" in out
    data = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    jsonschema.validate(data, SCHEMA, format_checker=jsonschema.FormatChecker())
    assert data["cost_source"] == "actual" and set(data["cost_period"]) == {"from", "to"}
    assert data["summary"]["actual_costs"] == 10 and data["summary"]["monthly_savings"] == 457.62
    by_name = {f["name"]: f for f in data["findings"]}
    assert (by_name["build-agent-02"]["monthly_cost"], by_name["build-agent-02"]["cost_source"]) == (139.82, "actual")
    assert (by_name["awf-stopped-vm"]["monthly_cost"], by_name["awf-stopped-vm"]["cost_source"]) == (8.18, "retail")
    assert by_name["sap-test-db-data"]["monthly_savings"] == 47.76
    assert by_name["erp-db-before-migration"]["monthly_cost"] == 6.12  # used size, not the provisioned upper bound
    assert all(f["cost_source"] == "retail" for f in data["cleanup"])


def test_actual_costs_in_report_csv_sarif_and_summary(actual_reports):
    out_dir, _ = actual_reports
    md = (out_dir / "report.md").read_text(encoding="utf-8")
    assert "Kostenquelle: 10 von 15 Beträgen sind Ist-Kosten aus Azure Cost Management" in md
    assert "| Kosten €/Monat | Einsparung €/Monat | Quelle | Empfehlung |" in md
    assert "| 139,82 € | 139,82 € | Ist-Kosten |" in md and "| 8,18 € | 8,18 € | Listenpreis |" in md
    assert "*Kosten: Ist-Kosten aus Azure Cost Management, wo vorhanden" in md
    html = (out_dir / "report.html").read_text(encoding="utf-8")
    assert "<th>Quelle</th>" in html and "<td>Ist-Kosten</td>" in html and "Kostenquelle: 10 von 15" in html
    rows = {r["name"]: r for r in csv.DictReader(io.StringIO((out_dir / "report.csv").read_text("utf-8")))}
    assert rows["build-agent-02"]["cost_source"] == "actual" and rows["awf-orphaned-pip"]["cost_source"] == "retail"
    sarif = json.loads((out_dir / "report.sarif").read_text(encoding="utf-8"))
    sources = {r["properties"]["costSource"] for r in sarif["runs"][0]["results"]}
    assert sources == {"actual", "retail"}
    summary = (out_dir / "summary.md").read_text(encoding="utf-8")
    assert "Kostenquelle: 10 von 15 Beträgen Ist-Kosten (Azure Cost Management" in summary


def test_retail_run_has_no_source_column(tmp_path):
    assert cli.main(["--demo", "--format", "md,html,json", "--out-dir", str(tmp_path)]) == 0
    assert "Quelle" not in (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "<th>Quelle</th>" not in (tmp_path / "report.html").read_text(encoding="utf-8")
    data = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert (data["cost_source"], data["cost_period"], data["summary"]["actual_costs"]) == ("retail", None, 0)
    assert {f["cost_source"] for f in data["findings"]} == {"retail"}


@pytest.fixture
def real_backends(monkeypatch):
    used = {}
    monkeypatch.setattr(cli, "resource_graph_runner", lambda scope: demo_runner())
    monkeypatch.setattr(cli, "retail_api_fetcher", lambda cache_file, currency: demo_fetcher())

    def query_factory(period):
        used["period"] = period
        demo = demo_cost_query()

        def query(subscription_id):
            used.setdefault("subscriptions", []).append(subscription_id)
            if subscription_id.startswith("0000"):
                raise CostManagementError(
                    "HTTP 403: denied (needs the Cost Management Reader role on the subscription)"
                )
            return demo(subscription_id)

        return query

    monkeypatch.setattr(cli, "cost_management_query", query_factory)
    return used


def test_real_run_falls_back_to_retail_for_a_failed_subscription(real_backends, tmp_path, capsys):
    assert cli.main(["--all-subscriptions", "--cost-source", "actual", "--out-dir", str(tmp_path)]) == 0
    assert real_backends["subscriptions"] == [
        "00000000-0000-0000-0000-000000000000",
        "11111111-1111-1111-1111-111111111111",
    ]  # only subscriptions with findings, each once
    assert real_backends["period"] == last_days(date.today())
    captured = capsys.readouterr()
    assert "warning: Cost Management query for subscription 00000000" in captured.err
    assert "6 priced from Cost Management" in captured.out  # the 6 findings of subscription 1111


def test_real_run_with_another_billing_currency(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "resource_graph_runner", lambda scope: demo_runner())
    monkeypatch.setattr(cli, "retail_api_fetcher", lambda cache_file, currency: demo_fetcher())

    def query_factory(period):
        demo = demo_cost_query()
        return lambda sub: {rid: ActualCost(c.amount, "EUR") for rid, c in demo(sub).items()}

    monkeypatch.setattr(cli, "cost_management_query", query_factory)
    args = ["--subscription", "s", "--cost-source", "actual", "--currency", "CHF", "--out-dir", str(tmp_path)]
    assert cli.main(args) == 0
    captured = capsys.readouterr()
    assert "note: Cost Management reports 10 finding(s) in another currency than CHF" in captured.err
    assert "0 priced from Cost Management" in captured.out


def test_retail_run_does_not_query_cost_management(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "resource_graph_runner", lambda scope: demo_runner())
    monkeypatch.setattr(cli, "retail_api_fetcher", lambda cache_file, currency: demo_fetcher())
    monkeypatch.setattr(cli, "cost_management_query", lambda period: pytest.fail("must not query Cost Management"))
    assert cli.main(["--subscription", "s", "--out-dir", str(tmp_path)]) == 0
