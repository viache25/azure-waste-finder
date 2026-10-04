"""Price findings with the public Azure Retail Prices API (no login needed).

Docs: https://learn.microsoft.com/rest/api/cost-management/retail-prices/azure-retail-prices
Retail = list price. Real customer prices can be lower (EA/CSP discounts, reservations).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, NamedTuple

import requests

from waste_finder.models import HOURS_PER_MONTH, Finding
from waste_finder.registry import REGISTRY

API_URL = "https://prices.azure.com/api/retail/prices"
CURRENCY = "EUR"

# One item of the Retail Prices API response.
PriceItem = dict[str, Any]

# An item fetcher takes an OData filter and returns the matching price items.
PriceFetcher = Callable[[str], list[PriceItem]]


class Price(NamedTuple):
    """What a pricing strategy found out about one finding (amounts per month, in the configured currency)."""

    cost: float | None  # what the resource costs now; None = no price found
    note: str  # how it was priced
    savings: float | None = None  # what acting saves when that is less than the cost (e.g. a downgrade)


PricingStrategy = Callable[[Finding, PriceFetcher], Price]

# Managed disk tiers: (max size in GB, tier number). Same numbers for S, E and P disks.
DISK_TIERS = [
    (4, 1),
    (8, 2),
    (16, 3),
    (32, 4),
    (64, 6),
    (128, 10),
    (256, 15),
    (512, 20),
    (1024, 30),
    (2048, 40),
    (4096, 50),
    (8192, 60),
    (16384, 70),
    (32767, 80),
]
DISK_PREFIX = {"Standard": "S", "StandardSSD": "E", "Premium": "P"}
# Standard HDD disks start at S4 (32 GB).
MIN_TIER = {"S": 4}
# Downgrade candidates are compared with Standard HDD (LRS only; HDD has no ZRS).
DOWNGRADE_TARGET_SKU = "Standard_LRS"

# Snapshot SKU (Standard_LRS, Standard_ZRS, Premium_LRS) -> Retail API product of its storage type.
# Incremental snapshots are always stored on Standard HDD, so they carry a Standard_* SKU.
SNAPSHOT_PRODUCTS = {"Standard": "Standard HDD Managed Disks", "Premium": "Premium SSD Managed Disks"}

# Standard load balancer: one hourly meter covers the first 5 load-balancing + outbound rules, each further rule
# bills the overage meter. Without rules there is no hourly charge (Azure pricing FAQ). Prices are global.
LB_INCLUDED_RULES = 5

PUBLIC_IP_METERS = {
    "Standard": "Standard IPv4 Static Public IP",
    "Basic": "Basic IPv4 Static Public IP Address",
}


def disk_sku_name(storage_sku: str, size_gb: int) -> str | None:
    """'Standard_LRS', 30 -> 'S4 LRS'. None if the disk type isn't supported."""
    kind, _, redundancy = storage_sku.partition("_")
    prefix = DISK_PREFIX.get(kind)
    if not prefix or not redundancy:
        return None
    for max_gb, tier in DISK_TIERS:
        if size_gb <= max_gb and tier >= MIN_TIER.get(prefix, 1):
            return f"{prefix}{tier} {redundancy}"
    return None


def _vm_price(finding: Finding, fetch: PriceFetcher) -> Price:
    items = fetch(
        "serviceName eq 'Virtual Machines' and priceType eq 'Consumption' "
        f"and armSkuName eq '{finding.sku}' and armRegionName eq '{finding.location}'"
    )
    windows = (finding.os_type or "").lower() == "windows"
    for item in items:
        name = f"{item.get('skuName', '')} {item.get('meterName', '')}"
        if "Spot" in name or "Low Priority" in name or item.get("unitOfMeasure") != "1 Hour":
            continue
        if ("Windows" in item.get("productName", "")) != windows:
            continue
        return Price(item["retailPrice"] * HOURS_PER_MONTH, f"{item['retailPrice']} €/h × {HOURS_PER_MONTH} h")
    return Price(None, "no VM price found")


def _disk_price(finding: Finding, fetch: PriceFetcher) -> Price:
    sku_name = disk_sku_name(finding.sku, finding.size_gb or 0)
    if not sku_name:
        return Price(None, f"disk type {finding.sku} not supported")
    items = fetch(
        "serviceName eq 'Storage' and priceType eq 'Consumption' "
        f"and skuName eq '{sku_name}' and armRegionName eq '{finding.location}'"
    )
    for item in items:
        # Exactly '<tier> Disk': SSD tiers also list a '<tier> Disk Mount' meter (per mount of a shared disk).
        if (
            item.get("unitOfMeasure") == "1/Month"
            and item.get("meterName") == f"{sku_name} Disk"
            and "Managed Disks" in item.get("productName", "")
        ):
            return Price(item["retailPrice"], f"tier {sku_name}, monthly flat price")
    return Price(None, f"no price for {sku_name}")


def _disk_downgrade_price(finding: Finding, fetch: PriceFetcher) -> Price:
    """Cost of the current SSD tier; savings = difference to the Standard HDD tier of the same size (D6)."""
    current = _disk_price(finding, fetch)
    if current.cost is None:
        return current
    hdd_tier = disk_sku_name(DOWNGRADE_TARGET_SKU, finding.size_gb or 0)
    hdd = _disk_price(replace(finding, sku=DOWNGRADE_TARGET_SKU), fetch)
    if hdd.cost is None:
        # Without the reference price the savings are unknown; the full cost would overstate them.
        return Price(None, f"{current.note}; {hdd.note} to compare with")
    savings = max(0.0, current.cost - hdd.cost)  # tiny SSDs can be cheaper than the smallest HDD tier (S4)
    return Price(current.cost, f"{current.note}; as Standard HDD ({hdd_tier}) {hdd.cost} €/month", savings)


def _ip_price(finding: Finding, fetch: PriceFetcher) -> Price:
    meter = PUBLIC_IP_METERS.get(finding.sku)
    if not meter:
        return Price(None, f"public IP SKU {finding.sku} not supported")
    items = [
        i
        for i in fetch(f"serviceName eq 'Virtual Network' and priceType eq 'Consumption' and meterName eq '{meter}'")
        if i.get("unitOfMeasure") == "1 Hour"
    ]
    # Prefer the exact region, fall back to any region (IP prices are the same almost everywhere).
    items.sort(key=lambda i: i.get("armRegionName") != finding.location)
    if not items:
        return Price(None, "no public IP price found")
    price = items[0]["retailPrice"]
    return Price(price * HOURS_PER_MONTH, f"{price} €/h × {HOURS_PER_MONTH} h")


def _snapshot_price(finding: Finding, fetch: PriceFetcher) -> Price:
    """GB-month price of the snapshot meter × provisioned size: an upper bound, Azure bills the used size."""
    kind, _, redundancy = finding.sku.partition("_")
    product = SNAPSHOT_PRODUCTS.get(kind)
    if not product or not redundancy:
        return Price(None, f"snapshot SKU {finding.sku} not supported")
    if not finding.size_gb:
        return Price(None, "snapshot size unknown")
    items = fetch(
        "serviceName eq 'Storage' and priceType eq 'Consumption' "
        f"and productName eq '{product}' and skuName eq 'Snapshots {redundancy}' "
        f"and armRegionName eq '{finding.location}'"
    )
    for item in items:
        if item.get("unitOfMeasure") == "1 GB/Month" and item.get("meterName", "").endswith("Snapshots"):
            price = item["retailPrice"]
            return Price(
                price * finding.size_gb, f"{price} €/GB-month × {finding.size_gb} GB (provisioned size, upper bound)"
            )
    return Price(None, f"no snapshot price for {product}, {redundancy}")


def _app_service_plan_price(finding: Finding, fetch: PriceFetcher) -> Price:
    """Hourly plan price × 730 × instances. The Retail API writes 'P1 v3' where ARM writes 'P1v3'."""
    items = fetch(
        f"serviceName eq 'Azure App Service' and priceType eq 'Consumption' and armRegionName eq '{finding.location}'"
    )
    linux = (finding.os_type or "").lower() == "linux"
    wanted = finding.sku.replace(" ", "").lower()
    instances = finding.quantity or 1  # a plan always runs at least one instance
    for item in items:
        product = item.get("productName", "")
        if item.get("unitOfMeasure") != "1 Hour" or " Plan" not in product or product.endswith(" - Linux") != linux:
            continue
        if item.get("skuName", "").replace(" ", "").lower() == wanted:
            price = item["retailPrice"]
            note = f"{price} €/h × {HOURS_PER_MONTH} h × {instances} instance(s)"
            return Price(price * HOURS_PER_MONTH * instances, note)
    return Price(None, f"no App Service plan price for {finding.sku} ({'Linux' if linux else 'Windows'})")


def _prefer_region(items: list[PriceItem], location: str) -> list[PriceItem]:
    """Exact region first, then the 'Global' price list, then anything else (e.g. 'US Gov')."""
    return sorted(items, key=lambda i: (i.get("armRegionName") != location, i.get("armRegionName") != "Global"))


def _nat_gateway_price(finding: Finding, fetch: PriceFetcher) -> Price:
    """Hourly gateway meter × 730; data processed is 0 when no subnet uses the gateway."""
    meter = f"{finding.sku} Gateway"
    items = [
        i
        for i in fetch(f"serviceName eq 'NAT Gateway' and priceType eq 'Consumption' and meterName eq '{meter}'")
        if i.get("unitOfMeasure") == "1 Hour"
    ]
    if not items:
        return Price(None, f"no hourly NAT gateway price for SKU {finding.sku or 'unknown'}")
    price = _prefer_region(items, finding.location)[0]["retailPrice"]
    return Price(price * HOURS_PER_MONTH, f"{price} €/h × {HOURS_PER_MONTH} h")


def _load_balancer_price(finding: Finding, fetch: PriceFetcher) -> Price:
    """Rules-based hourly price; a load balancer without rules bills nothing per hour (-> info finding)."""
    rules = finding.quantity or 0
    if rules == 0:
        return Price(0.0, "no load-balancing or outbound rules: no hourly charge")
    items = [
        i
        for i in fetch(f"serviceName eq 'Load Balancer' and priceType eq 'Consumption' and skuName eq '{finding.sku}'")
        if i.get("unitOfMeasure") in ("1 Hour", "1/Hour")
    ]

    def meter(kind: str) -> float | None:
        name = f"{finding.sku} {kind} LB Rules and Outbound Rules"  # the '... - Free' meters do not match
        matches = _prefer_region([i for i in items if i.get("meterName") == name], finding.location)
        return matches[0]["retailPrice"] if matches else None

    included, overage = meter("Included"), meter("Overage")
    extra = max(0, rules - LB_INCLUDED_RULES)
    if included is None or (extra and overage is None):
        return Price(None, f"no load balancer rule price for SKU {finding.sku}")
    hourly = included + extra * (overage or 0.0)
    note = f"{included} €/h for up to {LB_INCLUDED_RULES} rules"
    if extra:
        note += f" + {extra} × {overage} €/h"
    return Price(hourly * HOURS_PER_MONTH, f"{note}, × {HOURS_PER_MONTH} h ({rules} rules)")


def _free(finding: Finding, fetch: PriceFetcher) -> Price:
    """Hygiene findings: the resource type has no charge of its own."""
    return Price(0.0, "no charge for this resource type")


# strategy name (registry.Rule.pricing) -> function
STRATEGIES: dict[str, PricingStrategy] = {
    "vm_compute": _vm_price,
    "managed_disk": _disk_price,
    "public_ip": _ip_price,
    "snapshot": _snapshot_price,
    "app_service_plan": _app_service_plan_price,
    "nat_gateway": _nat_gateway_price,
    "load_balancer": _load_balancer_price,
    "disk_downgrade": _disk_downgrade_price,
    "free": _free,
}

# Strategies whose savings are only part of the cost (D6). With actual costs, their savings keep the retail
# ratio of savings to cost; without a retail result the savings are unknown and the finding stays unpriced.
PARTIAL_SAVINGS_STRATEGIES = frozenset({"disk_downgrade"})


def price_findings(findings: list[Finding], fetch: PriceFetcher) -> list[Finding]:
    for f in findings:
        price = STRATEGIES[REGISTRY[f.rule].pricing](f, fetch)
        f.monthly_cost_eur = round(price.cost, 2) if price.cost is not None else None
        f.monthly_savings_eur = round(price.savings, 2) if price.savings is not None else None
        f.price_note = price.note
        f.cost_source = "retail" if price.cost is not None else None
        if f.savings_eur == 0:
            # Saves nothing, e.g. a load balancer without rules (free) or a downgrade that is not cheaper.
            f.severity = "info"
    return findings


def retail_api_fetcher(
    cache_file: Path | None = None, ttl_seconds: int = 24 * 3600, currency: str = CURRENCY
) -> PriceFetcher:
    """Real fetcher: calls the public API, follows paging, caches answers in a JSON file (one file per currency)."""
    cache: dict[str, dict[str, Any]] = {}
    if cache_file and cache_file.exists():
        cache = json.loads(cache_file.read_text(encoding="utf-8"))

    def fetch(odata_filter: str) -> list[PriceItem]:
        hit = cache.get(odata_filter)
        if hit and time.time() - hit["ts"] < ttl_seconds:
            cached: list[PriceItem] = hit["items"]
            return cached
        items: list[PriceItem] = []
        url: str | None = API_URL
        params: dict[str, str] | None = {"currencyCode": f"'{currency}'", "$filter": odata_filter}
        while url:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            body = resp.json()
            items.extend(body.get("Items", []))
            url, params = body.get("NextPageLink"), None  # next link already has the query
        cache[odata_filter] = {"ts": time.time(), "items": items}
        if cache_file:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(cache), encoding="utf-8")
        return items

    return fetch
