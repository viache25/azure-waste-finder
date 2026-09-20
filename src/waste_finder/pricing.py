"""Price findings with the public Azure Retail Prices API (no login needed).

Docs: https://learn.microsoft.com/rest/api/cost-management/retail-prices/azure-retail-prices
Retail = list price. Real customer prices can be lower (EA/CSP discounts, reservations).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

import requests

from waste_finder.models import HOURS_PER_MONTH, Finding

API_URL = "https://prices.azure.com/api/retail/prices"
CURRENCY = "EUR"

# An item fetcher takes an OData filter and returns the matching price items.
PriceFetcher = Callable[[str], list[dict]]

# Managed disk tiers: (max size in GB, tier number). Same numbers for S, E and P disks.
DISK_TIERS = [
    (4, 1), (8, 2), (16, 3), (32, 4), (64, 6), (128, 10), (256, 15), (512, 20),
    (1024, 30), (2048, 40), (4096, 50), (8192, 60), (16384, 70), (32767, 80),
]
DISK_PREFIX = {"Standard": "S", "StandardSSD": "E", "Premium": "P"}
# Standard HDD disks start at S4 (32 GB).
MIN_TIER = {"S": 4}

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


def _vm_price(finding: Finding, fetch: PriceFetcher) -> tuple[float | None, str]:
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
        return item["retailPrice"] * HOURS_PER_MONTH, f"{item['retailPrice']} €/h × {HOURS_PER_MONTH} h"
    return None, "no VM price found"


def _disk_price(finding: Finding, fetch: PriceFetcher) -> tuple[float | None, str]:
    sku_name = disk_sku_name(finding.sku, finding.size_gb or 0)
    if not sku_name:
        return None, f"disk type {finding.sku} not supported"
    items = fetch(
        "serviceName eq 'Storage' and priceType eq 'Consumption' "
        f"and skuName eq '{sku_name}' and armRegionName eq '{finding.location}'"
    )
    for item in items:
        if item.get("unitOfMeasure") == "1/Month" and "Disk" in item.get("meterName", ""):
            return item["retailPrice"], f"tier {sku_name}, monthly flat price"
    return None, f"no price for {sku_name}"


def _ip_price(finding: Finding, fetch: PriceFetcher) -> tuple[float | None, str]:
    meter = PUBLIC_IP_METERS.get(finding.sku)
    if not meter:
        return None, f"public IP SKU {finding.sku} not supported"
    items = [
        i for i in fetch(f"serviceName eq 'Virtual Network' and priceType eq 'Consumption' and meterName eq '{meter}'")
        if i.get("unitOfMeasure") == "1 Hour"
    ]
    # Prefer the exact region, fall back to any region (IP prices are the same almost everywhere).
    items.sort(key=lambda i: i.get("armRegionName") != finding.location)
    if not items:
        return None, "no public IP price found"
    price = items[0]["retailPrice"]
    return price * HOURS_PER_MONTH, f"{price} €/h × {HOURS_PER_MONTH} h"


PRICERS = {
    "stopped_vm": _vm_price,
    "unattached_disk": _disk_price,
    "orphaned_public_ip": _ip_price,
}


def price_findings(findings: list[Finding], fetch: PriceFetcher) -> list[Finding]:
    for f in findings:
        cost, note = PRICERS[f.rule](f, fetch)
        f.monthly_cost_eur = round(cost, 2) if cost is not None else None
        f.price_note = note
    return findings


def retail_api_fetcher(cache_file: Path | None = None, ttl_seconds: int = 24 * 3600) -> PriceFetcher:
    """Real fetcher: calls the public API, follows paging, caches answers in a JSON file."""
    cache: dict = {}
    if cache_file and cache_file.exists():
        cache = json.loads(cache_file.read_text(encoding="utf-8"))

    def fetch(odata_filter: str) -> list[dict]:
        hit = cache.get(odata_filter)
        if hit and time.time() - hit["ts"] < ttl_seconds:
            return hit["items"]
        items: list[dict] = []
        url: str | None = API_URL
        params: dict | None = {"currencyCode": f"'{CURRENCY}'", "$filter": odata_filter}
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
