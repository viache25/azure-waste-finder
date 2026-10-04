"""Actual costs from the Azure Cost Management Query API (`--cost-source actual`).

Docs: https://learn.microsoft.com/rest/api/cost-management/query/usage
One query per subscription that has findings: amortized cost of the last 30 full days, grouped by resource ID.
Needs the Cost Management Reader role (or Reader) on the subscription. A finding without a cost row, in another
currency, or in a subscription whose query failed keeps its retail price (per-finding fallback).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any, NamedTuple

import requests

from waste_finder.models import Finding
from waste_finder.pricing import PARTIAL_SAVINGS_STRATEGIES
from waste_finder.registry import REGISTRY

if TYPE_CHECKING:
    from azure.core.credentials import TokenCredential

MANAGEMENT_URL = "https://management.azure.com"
TOKEN_SCOPE = f"{MANAGEMENT_URL}/.default"
API_VERSION = "2023-11-01"
LOOKBACK_DAYS = 30
# The cost column is called "Cost" (asked for below) or, for some older account types, "PreTaxCost".
COST_COLUMNS = ("Cost", "PreTaxCost")
MAX_RETRIES = 3  # on HTTP 429 (Cost Management throttles per tenant and scope)
MAX_RETRY_AFTER_SECONDS = 60


class CostManagementError(RuntimeError):
    """A query failed; the CLI prints it and keeps the retail prices of that subscription."""


class CostPeriod(NamedTuple):
    start: date
    end: date  # inclusive

    def label(self) -> str:
        """German report label: '04.09.2026 bis 03.10.2026'."""
        return f"{self.start:%d.%m.%Y} bis {self.end:%d.%m.%Y}"


@dataclass(frozen=True)
class ActualCost:
    amount: float  # cost of the whole period
    currency: str


# Lower-case resource ID -> its cost in the period. Cost Management returns resource IDs in lower case.
ActualCosts = dict[str, ActualCost]

# Takes a subscription ID, returns the actual costs of its resources.
CostQuery = Callable[[str], ActualCosts]


@dataclass(frozen=True)
class ApplyResult:
    actual: int  # findings now priced from Cost Management
    other_currency: int  # findings with a cost row in another currency (kept at retail)


def last_days(today: date, days: int = LOOKBACK_DAYS) -> CostPeriod:
    """The last `days` full days before today (today's data is still incomplete)."""
    end = today - timedelta(days=1)
    return CostPeriod(end - timedelta(days=days - 1), end)


def query_body(period: CostPeriod) -> dict[str, Any]:
    return {
        "type": "AmortizedCost",  # reservations and savings plans spread over the resources that use them
        "timeframe": "Custom",
        "timePeriod": {"from": f"{period.start.isoformat()}T00:00:00Z", "to": f"{period.end.isoformat()}T23:59:59Z"},
        "dataset": {
            "granularity": "None",
            "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
            "grouping": [{"type": "Dimension", "name": "ResourceId"}],
        },
    }


def parse_query_result(body: dict[str, Any]) -> ActualCosts:
    """Rows of one result page -> costs per lower-case resource ID."""
    try:
        properties = body["properties"]
        names = [column["name"] for column in properties["columns"]]
        cost_index = next(names.index(name) for name in COST_COLUMNS if name in names)
        id_index, currency_index = names.index("ResourceId"), names.index("Currency")
        rows = properties["rows"]
    except (KeyError, TypeError, ValueError, StopIteration) as e:
        raise CostManagementError(f"unexpected Cost Management response: {e!r}") from e
    costs: ActualCosts = {}
    for row in rows:
        resource_id = str(row[id_index] or "").lower()
        if not resource_id:  # costs without a resource, e.g. support plans or marketplace fees
            continue
        previous = costs.get(resource_id)
        amount = float(row[cost_index]) + (previous.amount if previous else 0.0)
        costs[resource_id] = ActualCost(amount, str(row[currency_index]).upper())
    return costs


def _retry_after(response: requests.Response) -> float:
    for header in ("x-ms-ratelimit-microsoft.costmanagement-qpu-retry-after", "Retry-After"):
        value = response.headers.get(header)
        if value and value.strip().isdigit():
            return min(float(value), MAX_RETRY_AFTER_SECONDS)
    return 5.0


def _error_message(response: requests.Response) -> str:
    try:
        message = str(response.json()["error"]["message"])
    except (ValueError, KeyError, TypeError):
        message = response.reason or ""
    hint = " (needs the Cost Management Reader role on the subscription)" if response.status_code in (401, 403) else ""
    return f"HTTP {response.status_code}: {message}{hint}"


def cost_management_query(
    period: CostPeriod,
    credential: TokenCredential | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> CostQuery:
    """Real query: Cost Management Query API, authenticated via DefaultAzureCredential (az login)."""
    if credential is None:
        from azure.identity import DefaultAzureCredential

        credential = DefaultAzureCredential()
    token_credential = credential

    def post(url: str, body: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {token_credential.get_token(TOKEN_SCOPE).token}"}
        for attempt in range(MAX_RETRIES + 1):
            response = requests.post(url, json=body, headers=headers, timeout=60)
            if response.status_code == 429 and attempt < MAX_RETRIES:
                sleep(_retry_after(response))
                continue
            if response.status_code >= 400:
                raise CostManagementError(_error_message(response))
            data: dict[str, Any] = response.json()
            return data
        raise CostManagementError("still throttled (HTTP 429) after retries")  # pragma: no cover

    def query(subscription_id: str) -> ActualCosts:
        url: str | None = (
            f"{MANAGEMENT_URL}/subscriptions/{subscription_id}/providers/Microsoft.CostManagement/query"
            f"?api-version={API_VERSION}"
        )
        body = query_body(period)
        costs: ActualCosts = {}
        while url:
            page = post(url, body)
            for resource_id, cost in parse_query_result(page).items():
                previous = costs.get(resource_id)
                costs[resource_id] = ActualCost(cost.amount + (previous.amount if previous else 0.0), cost.currency)
            url = page["properties"].get("nextLink")  # full URL with $skiptoken; same body again
        return costs

    return query


def collect_actual_costs(query: CostQuery, subscriptions: Iterable[str], warn: Callable[[str], None]) -> ActualCosts:
    """Query each subscription once; a failed query is reported and its findings keep retail prices."""
    costs: ActualCosts = {}
    for subscription_id in sorted(set(subscriptions)):
        try:
            costs.update(query(subscription_id))
        except (CostManagementError, requests.RequestException) as e:
            warn(f"Cost Management query for subscription {subscription_id} failed, using retail prices: {e}")
    return costs


def apply_actual_costs(findings: list[Finding], costs: ActualCosts, currency: str, period: CostPeriod) -> ApplyResult:
    """Replace retail prices by actual costs where Cost Management has a row in the report currency."""
    actual = other_currency = 0
    for f in findings:
        cost = costs.get(f.resource_id.lower())
        if cost is None:
            continue
        if cost.currency != currency:
            other_currency += 1
            continue
        partial = REGISTRY[f.rule].pricing in PARTIAL_SAVINGS_STRATEGIES
        retail_cost, retail_savings = f.monthly_cost_eur, f.monthly_savings_eur
        if partial and (retail_cost is None or retail_savings is None):
            continue  # savings unknown: the full actual cost would overstate them
        amount = round(cost.amount, 2)
        retail_note = f"retail: {f.price_note}" if f.price_note else "no retail price"
        f.monthly_cost_eur = amount
        if partial and retail_cost and retail_savings is not None:
            # A downgrade keeps the retail ratio of savings to cost (the discount applies to both tiers).
            f.monthly_savings_eur = round(amount * retail_savings / retail_cost, 2)
        elif partial:
            f.monthly_savings_eur = 0.0
        f.price_note = f"actual: amortized cost {period.start} to {period.end} (Cost Management); {retail_note}"
        f.cost_source = "actual"
        f.severity = "info" if f.savings_eur == 0 else REGISTRY[f.rule].severity
        actual += 1
    return ApplyResult(actual, other_currency)
