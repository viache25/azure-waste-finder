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


@pytest.mark.parametrize(
    ("sku", "os_type", "instances", "expected"),
    [
        ("B1", "Linux", 1, round(0.0158 * 730, 2)),
        ("B1", "Windows", 1, round(0.066 * 730, 2)),  # same SKU, Windows plan product
        ("S1", "Windows", 2, round(0.088 * 730 * 2, 2)),  # every instance bills
        ("P1v3", "Linux", 1, round(0.1566 * 730, 2)),  # ARM 'P1v3' = Retail 'P1 v3'
        ("B1", "Linux", None, round(0.0158 * 730, 2)),  # unknown capacity: at least one instance
    ],
)
def test_app_service_plan_price(sku, os_type, instances, expected):
    [f] = price_findings([make("empty_app_service_plan", sku, os_type=os_type, quantity=instances)], demo_fetcher())
    assert f.monthly_cost_eur == expected
    assert f"× {instances or 1} instance(s)" in f.price_note


@pytest.mark.parametrize(("sku", "os_type"), [("EP1", "Windows"), ("P1v3", "Windows"), ("SNISSL", "Windows")])
def test_app_service_plan_without_price(sku, os_type):
    [f] = price_findings([make("empty_app_service_plan", sku, os_type=os_type, quantity=1)], demo_fetcher())
    assert f.monthly_cost_eur is None
    assert f"no App Service plan price for {sku} (Windows)" in f.price_note


def test_nat_gateway_bills_per_hour_with_global_price():
    [f] = price_findings([make("idle_nat_gateway", "Standard")], demo_fetcher())
    assert f.monthly_cost_eur == round(0.0396 * 730, 2)  # 'Global' price, not the 'US Gov' one
    assert f.severity == "medium"


@pytest.mark.parametrize("sku", ["StandardV2", ""])
def test_nat_gateway_without_hourly_meter_is_unpriced(sku):
    [f] = price_findings([make("idle_nat_gateway", sku)], demo_fetcher())
    assert f.monthly_cost_eur is None and "no hourly NAT gateway price" in f.price_note


@pytest.mark.parametrize(
    ("rules", "expected"),
    [
        (1, round(0.022 * 730, 2)),
        (5, round(0.022 * 730, 2)),  # the first 5 rules share one hourly meter
        (7, round((0.022 + 2 * 0.0088) * 730, 2)),  # each further rule bills the overage meter
    ],
)
def test_load_balancer_bills_for_rules(rules, expected):
    [f] = price_findings([make("idle_load_balancer", "Standard", quantity=rules, severity="low")], demo_fetcher())
    assert f.monthly_cost_eur == expected and f.severity == "low"  # billed: keeps the rule severity
    assert f"({rules} rules)" in f.price_note


@pytest.mark.parametrize("rules", [0, None])
def test_load_balancer_without_rules_is_free_info_finding(rules):
    [f] = price_findings([make("idle_load_balancer", "Standard", quantity=rules, severity="low")], demo_fetcher())
    assert f.monthly_cost_eur == 0.0 and f.severity == "info"
    assert "no hourly charge" in f.price_note


def test_load_balancer_without_price():
    [f] = price_findings([make("idle_load_balancer", "Gateway", quantity=1)], demo_fetcher())
    assert f.monthly_cost_eur is None and "no load balancer rule price for SKU Gateway" in f.price_note


def test_load_balancer_overage_needs_its_meter():
    def fetch(odata_filter):
        return [i for i in demo_fetcher()(odata_filter) if "Overage" not in i["meterName"]]

    [few] = price_findings([make("idle_load_balancer", "Standard", quantity=3)], fetch)
    [many] = price_findings([make("idle_load_balancer", "Standard", quantity=6)], fetch)
    assert few.monthly_cost_eur == round(0.022 * 730, 2) and many.monthly_cost_eur is None


def test_only_free_findings_become_info():
    [unpriced] = price_findings([make("stopped_vm", "Standard_Unknown", severity="high")], demo_fetcher())
    assert unpriced.severity == "high"


def test_disk_price_ignores_the_disk_mount_meter():
    # demo/prices.json lists 'E10 LRS Disk Mount' (1.04, per mount of a shared disk) before 'E10 LRS Disk'.
    [f] = price_findings([make("unattached_disk", "StandardSSD_LRS", size_gb=128)], demo_fetcher())
    assert f.monthly_cost_eur == 8.45


@pytest.mark.parametrize(
    ("sku", "size", "cost", "savings", "hdd"),
    [
        ("Premium_LRS", 512, 67.58, round(67.58 - 19.15, 2), "S20 LRS"),
        ("StandardSSD_LRS", 128, 8.45, round(8.45 - 5.18, 2), "S10 LRS"),
        ("Premium_LRS", 64, 9.88, round(9.88 - 2.65, 2), "S6 LRS"),
    ],
)
def test_downgrade_savings_are_the_difference_to_standard_hdd(sku, size, cost, savings, hdd):
    [f] = price_findings([make("premium_disk_deallocated_vm", sku, size_gb=size)], demo_fetcher())
    assert (f.monthly_cost_eur, f.monthly_savings_eur, f.savings_eur) == (cost, savings, savings)
    assert f"as Standard HDD ({hdd})" in f.price_note and f.severity == "medium"


def test_downgrade_that_saves_nothing_is_info():
    # A 4 GB Standard SSD (E1, 0.26) is cheaper than the smallest Standard HDD tier (S4, 1.41).
    [f] = price_findings([make("premium_disk_deallocated_vm", "StandardSSD_LRS", size_gb=4)], demo_fetcher())
    assert (f.monthly_cost_eur, f.monthly_savings_eur, f.severity) == (0.26, 0.0, "info")


def test_downgrade_without_hdd_price_is_unpriced_not_full_cost():
    def fetch(odata_filter):
        return [] if "skuName eq 'S20 LRS'" in odata_filter else demo_fetcher()(odata_filter)

    [f] = price_findings([make("premium_disk_deallocated_vm", "Premium_LRS", size_gb=512)], fetch)
    assert f.monthly_cost_eur is None and f.savings_eur is None
    assert "no price for S20 LRS to compare with" in f.price_note


def test_downgrade_of_unpriced_disk():
    [f] = price_findings([make("premium_disk_deallocated_vm", "Premium_LRS", size_gb=1000)], demo_fetcher())
    assert f.monthly_cost_eur is None and "no price for P30 LRS" in f.price_note


@pytest.mark.parametrize("rule", ["orphaned_nic", "unattached_nsg", "empty_resource_group"])
def test_hygiene_findings_are_free(rule):
    [f] = price_findings([make(rule, "")], demo_fetcher())
    assert (f.monthly_cost_eur, f.savings_eur, f.severity, f.is_free) == (0.0, 0.0, "info", True)
    assert f.price_note == "no charge for this resource type"


def test_only_zero_cost_is_free():
    assert not make("stopped_vm", "x", monthly_cost_eur=None).is_free
    assert not make("premium_disk_deallocated_vm", "x", monthly_cost_eur=1.0, monthly_savings_eur=0.0).is_free
