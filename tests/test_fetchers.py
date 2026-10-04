"""The real Azure-facing fetchers, with the network and the SDK replaced by fakes."""

import json
from types import SimpleNamespace

import azure.identity
import azure.mgmt.resourcegraph
import pytest

from waste_finder import cli, pricing
from waste_finder.demo import demo_fetcher, demo_runner
from waste_finder.rules import Scope, resource_graph_runner


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


@pytest.fixture
def fake_api(monkeypatch):
    """Two pages: the first one points to the second via NextPageLink."""
    calls = []
    pages = {
        pricing.API_URL: {"Items": [{"retailPrice": 1.0}], "NextPageLink": "https://next"},
        "https://next": {"Items": [{"retailPrice": 2.0}], "NextPageLink": None},
    }

    def get(url, params=None, timeout=None):
        calls.append((url, params))
        return FakeResponse(pages[url])

    monkeypatch.setattr(pricing.requests, "get", get)
    return calls


def test_retail_fetcher_follows_pages_and_sends_currency(fake_api):
    items = pricing.retail_api_fetcher()("serviceName eq 'Storage'")
    assert [i["retailPrice"] for i in items] == [1.0, 2.0]
    assert fake_api[0][1] == {"currencyCode": "'EUR'", "$filter": "serviceName eq 'Storage'"}
    assert fake_api[1] == ("https://next", None)


def test_retail_fetcher_uses_file_cache(fake_api, tmp_path):
    cache_file = tmp_path / "cache" / "prices.json"
    pricing.retail_api_fetcher(cache_file=cache_file)("f")
    assert "f" in json.loads(cache_file.read_text(encoding="utf-8"))

    items = pricing.retail_api_fetcher(cache_file=cache_file)("f")
    assert len(items) == 2
    assert len(fake_api) == 2  # second fetcher answered from the file


def test_retail_fetcher_refetches_expired_cache(fake_api, tmp_path):
    cache_file = tmp_path / "prices.json"
    pricing.retail_api_fetcher(cache_file=cache_file)("f")
    pricing.retail_api_fetcher(cache_file=cache_file, ttl_seconds=0)("f")
    assert len(fake_api) == 4


@pytest.fixture
def fake_graph(monkeypatch):
    """Fake Resource Graph SDK: two pages linked by a skip token; returns the requests it got."""
    requests = []
    pages = [
        SimpleNamespace(data=[{"id": "1"}], skip_token="next"),
        SimpleNamespace(data=[{"id": "2"}], skip_token=None),
    ]

    class FakeClient:
        def __init__(self, credential):
            self.credential = credential

        def resources(self, request):
            requests.append(request)
            return pages[(len(requests) - 1) % 2]

    monkeypatch.setattr(azure.identity, "DefaultAzureCredential", lambda: "cred")
    monkeypatch.setattr(azure.mgmt.resourcegraph, "ResourceGraphClient", FakeClient)
    return requests


def test_resource_graph_runner_follows_skip_token(fake_graph):
    rows = resource_graph_runner(Scope(subscriptions=("sub-1", "sub-2")))("Resources | take 1")
    assert rows == [{"id": "1"}, {"id": "2"}]
    assert fake_graph[0].subscriptions == ["sub-1", "sub-2"]
    assert fake_graph[0].management_groups is None
    assert fake_graph[0].options.skip_token is None
    assert fake_graph[1].options.skip_token == "next"


def test_resource_graph_runner_management_group_scope(fake_graph):
    resource_graph_runner(Scope(management_group="mg-prod"))("Resources")
    assert fake_graph[0].management_groups == ["mg-prod"]
    assert fake_graph[0].subscriptions is None


def test_resource_graph_runner_all_subscriptions_scope(fake_graph):
    resource_graph_runner(Scope())("Resources")
    assert fake_graph[0].subscriptions is None and fake_graph[0].management_groups is None


def test_retail_fetcher_sends_configured_currency(fake_api):
    pricing.retail_api_fetcher(currency="CHF")("f")
    assert fake_api[0][1]["currencyCode"] == "'CHF'"


def test_cli_real_run_uses_azure_runner_and_retail_api(monkeypatch, tmp_path, capsys):
    used = {}

    def runner(scope):
        used["scope"] = scope
        return demo_runner()

    def fetcher(cache_file, currency):
        used["cache_file"], used["currency"] = cache_file, currency
        return demo_fetcher()

    monkeypatch.setattr(cli, "resource_graph_runner", runner)
    monkeypatch.setattr(cli, "retail_api_fetcher", fetcher)

    assert cli.main(["--subscription", "sub-1", "--subscription", "sub-2", "--out-dir", str(tmp_path)]) == 0
    assert used["scope"] == Scope(subscriptions=("sub-1", "sub-2"))
    assert (used["cache_file"].name, used["currency"]) == ("prices-eur.json", "EUR")
    assert "sub-1, sub-2" in (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "11 findings" in capsys.readouterr().out


@pytest.fixture
def fake_cli_backends(monkeypatch):
    used = {}

    def runner(scope):
        used["scope"] = scope
        return demo_runner()

    def fetcher(cache_file, currency):
        used["currency"] = currency
        return demo_fetcher()

    monkeypatch.setattr(cli, "resource_graph_runner", runner)
    monkeypatch.setattr(cli, "retail_api_fetcher", fetcher)
    monkeypatch.delenv("AZURE_SUBSCRIPTION_ID", raising=False)
    return used


@pytest.mark.parametrize(
    ("flags", "scope"),
    [
        (["--all-subscriptions"], Scope()),
        (["--management-group", "mg-prod"], Scope(management_group="mg-prod")),
    ],
)
def test_cli_scope_flags(fake_cli_backends, tmp_path, flags, scope):
    assert cli.main([*flags, "--out-dir", str(tmp_path)]) == 0
    assert fake_cli_backends["scope"] == scope


def test_cli_subscription_defaults_to_env(fake_cli_backends, monkeypatch, tmp_path):
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "env-sub")
    assert cli.main(["--out-dir", str(tmp_path)]) == 0
    assert fake_cli_backends["scope"] == Scope(subscriptions=("env-sub",))


def test_cli_scope_flags_are_exclusive(fake_cli_backends, tmp_path):
    with pytest.raises(SystemExit):
        cli.main(["--all-subscriptions", "--management-group", "mg", "--out-dir", str(tmp_path)])


def test_cli_passes_currency_to_retail_api(fake_cli_backends, tmp_path):
    assert cli.main(["--subscription", "s", "--currency", "chf", "--out-dir", str(tmp_path)]) == 0
    assert fake_cli_backends["currency"] == "CHF"
    md = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "CHF pro Monat" in md and "Listenpreise in CHF" in md
