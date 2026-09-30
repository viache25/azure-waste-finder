"""The real Azure-facing fetchers, with the network and the SDK replaced by fakes."""

import json
from types import SimpleNamespace

import azure.identity
import azure.mgmt.resourcegraph
import pytest

from waste_finder import cli, pricing
from waste_finder.demo import demo_fetcher, demo_runner
from waste_finder.rules import resource_graph_runner


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


def test_resource_graph_runner_follows_skip_token(monkeypatch):
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
            return pages[len(requests) - 1]

    monkeypatch.setattr(azure.identity, "DefaultAzureCredential", lambda: "cred")
    monkeypatch.setattr(azure.mgmt.resourcegraph, "ResourceGraphClient", FakeClient)

    rows = resource_graph_runner("sub-1")("Resources | take 1")
    assert rows == [{"id": "1"}, {"id": "2"}]
    assert requests[0].subscriptions == ["sub-1"]
    assert requests[0].options.skip_token is None
    assert requests[1].options.skip_token == "next"


def test_cli_real_run_uses_azure_runner_and_retail_api(monkeypatch, tmp_path, capsys):
    used = {}

    def runner(subscription):
        used["subscription"] = subscription
        return demo_runner()

    def fetcher(cache_file):
        used["cache_file"] = cache_file
        return demo_fetcher()

    monkeypatch.setattr(cli, "resource_graph_runner", runner)
    monkeypatch.setattr(cli, "retail_api_fetcher", fetcher)

    assert cli.main(["--subscription", "sub-1", "--out-dir", str(tmp_path)]) == 0
    assert used["subscription"] == "sub-1"
    assert used["cache_file"].name == "prices.json"
    assert "sub-1" in (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "6 findings" in capsys.readouterr().out
