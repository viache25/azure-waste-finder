import pytest

from waste_finder.demo import demo_fetcher
from waste_finder.models import Finding
from waste_finder.pricing import disk_sku_name, price_findings


def make(rule, sku, **kw):
    return Finding(rule=rule, resource_id="id", name="n", resource_group="rg",
                   location="westeurope", sku=sku, **kw)


@pytest.mark.parametrize("sku,size,expected", [
    ("Standard_LRS", 32, "S4 LRS"),
    ("Standard_LRS", 10, "S4 LRS"),      # HDD starts at S4
    ("StandardSSD_LRS", 10, "E3 LRS"),
    ("Premium_LRS", 512, "P20 LRS"),
    ("Premium_ZRS", 100, "P10 ZRS"),
    ("UltraSSD_LRS", 100, None),
    ("Premium_LRS", 99999, None),
])
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
