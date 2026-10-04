import pytest

from waste_finder.demo import demo_fetcher
from waste_finder.models import Finding
from waste_finder.pricing import disk_sku_name, price_findings


def make(rule, sku, **kw):
    return Finding(rule=rule, resource_id="id", name="n", resource_group="rg", location="westeurope", sku=sku, **kw)


@pytest.mark.parametrize(
    "sku,size,expected",
    [
        ("Standard_LRS", 32, "S4 LRS"),
        ("Standard_LRS", 10, "S4 LRS"),  # HDD starts at S4
        ("StandardSSD_LRS", 10, "E3 LRS"),
        ("Premium_LRS", 512, "P20 LRS"),
        ("Premium_ZRS", 100, "P10 ZRS"),
        ("UltraSSD_LRS", 100, None),
        ("Premium_LRS", 99999, None),
    ],
)
def test_disk_sku_name(sku, size, expected):
    assert disk_sku_name(sku, size) == expected


def test_vm_price_is_hourly_times_730_and_skips_spot_and_windows():
    [f] = price_findings([make("stopped_vm", "Standard_B1s", os_type="Linux")], demo_fetcher())
    assert f.monthly_cost_eur == round(0.0112 * 730, 2)


def test_windows_vm_uses_windows_price():
    [f] = price_findings([make("stopped_vm", "Standard_B1s", os_type="Windows")], demo_fetcher())
    assert f.monthly_cost_eur == round(0.0158 * 730, 2)


def test_disk_uses_monthly_meter_not_operations():
    [f] = price_findings([make("unattached_disk", "Standard_LRS", size_gb=32)], demo_fetcher())
    assert f.monthly_cost_eur == 1.41


def test_public_ip_price():
    [f] = price_findings([make("orphaned_public_ip", "Standard")], demo_fetcher())
    assert f.monthly_cost_eur == round(0.0046 * 730, 2)


def test_missing_price_is_none_not_zero():
    [f] = price_findings([make("stopped_vm", "Standard_Unknown")], demo_fetcher())
    assert f.monthly_cost_eur is None
    assert "no VM price" in f.price_note


def test_unsupported_disk_type_has_no_price():
    [f] = price_findings([make("unattached_disk", "UltraSSD_LRS", size_gb=100)], demo_fetcher())
    assert f.monthly_cost_eur is None
    assert "not supported" in f.price_note


def test_disk_tier_without_price_has_no_price():
    [f] = price_findings([make("unattached_disk", "Premium_LRS", size_gb=1000)], demo_fetcher())
    assert f.monthly_cost_eur is None
    assert "no price for P30 LRS" in f.price_note


def test_public_ip_falls_back_to_other_region():
    f = make("orphaned_public_ip", "Standard")
    f.location = "northeurope"
    [f] = price_findings([f], demo_fetcher())
    assert f.monthly_cost_eur == round(0.0046 * 730, 2)


@pytest.mark.parametrize("sku,note", [("Global", "not supported"), ("Basic", "no public IP price")])
def test_public_ip_without_price(sku, note):
    [f] = price_findings([make("orphaned_public_ip", sku)], demo_fetcher())
    assert f.monthly_cost_eur is None
    assert note in f.price_note


@pytest.mark.parametrize(
    ("sku", "size", "expected"),
    [
        ("Standard_LRS", 32, round(0.044 * 32, 2)),  # Standard HDD snapshot meter
        ("Standard_ZRS", 512, round(0.044 * 512, 2)),
        ("Premium_LRS", 128, round(0.1276 * 128, 2)),  # Premium SSD snapshot meter
    ],
)
def test_snapshot_price_is_gb_month_times_provisioned_size(sku, size, expected):
    [f] = price_findings([make("old_snapshot", sku, size_gb=size)], demo_fetcher())
    assert f.monthly_cost_eur == expected
    assert "upper bound" in f.price_note and f"× {size} GB" in f.price_note


@pytest.mark.parametrize(
    ("sku", "size", "note"),
    [
        ("UltraSSD_LRS", 100, "snapshot SKU UltraSSD_LRS not supported"),
        ("Standard", 100, "not supported"),
        ("Standard_LRS", None, "size unknown"),
        ("Premium_ZRS", 100, "no snapshot price for Premium SSD Managed Disks, ZRS"),
    ],
)
def test_snapshot_without_price(sku, size, note):
    [f] = price_findings([make("old_snapshot", sku, size_gb=size)], demo_fetcher())
    assert f.monthly_cost_eur is None
    assert note in f.price_note


def test_snapshot_price_filter_names_product_and_meter():
    filters = []

    def fetch(odata_filter):
        filters.append(odata_filter)
        return []

    price_findings([make("old_snapshot", "Premium_LRS", size_gb=10)], fetch)
    assert "productName eq 'Premium SSD Managed Disks'" in filters[0]
    assert "skuName eq 'Snapshots LRS'" in filters[0] and "armRegionName eq 'westeurope'" in filters[0]
