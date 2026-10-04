# Opt-in waste for the newer rules (enable_extra_waste = true). Smallest SKUs; the README lists the cost per hour.

# Snapshot of the orphaned disk. Snapshots bill per GB-month of used data; the source disk is empty,
# so this costs next to nothing. waste-finder reports it once it is older than snapshot_min_age_days
# (default 30); run with --snapshot-min-age 0 to see it right after `terraform apply`.
resource "azurerm_snapshot" "old" {
  count = var.enable_extra_waste ? 1 : 0

  name                = "${var.prefix}-old-snapshot"
  resource_group_name = azurerm_resource_group.demo.name
  location            = azurerm_resource_group.demo.location
  create_option       = "Copy"
  source_uri          = azurerm_managed_disk.orphaned.id
  incremental_enabled = true
  tags                = local.tags

  # No SAS export over the internet, like the source disk.
  public_network_access_enabled = false
  network_access_policy         = "DenyAll"
}

# App Service plan without any app: B1 Linux, one instance, the cheapest paid tier (~0.016 €/h).
# Free (F1) plans cost nothing, so they are not waste; B1 is the smallest plan that bills.
resource "azurerm_service_plan" "empty" {
  #checkov:skip=CKV_AZURE_211:A waste demo; the point is an idle paid plan, not a production-grade tier
  #checkov:skip=CKV_AZURE_212:One instance on purpose; failover instances would only multiply the waste
  #checkov:skip=CKV_AZURE_225:Zone redundancy needs Premium tiers and at least three instances
  count = var.enable_extra_waste ? 1 : 0

  name                = "${var.prefix}-empty-plan"
  resource_group_name = azurerm_resource_group.demo.name
  location            = azurerm_resource_group.demo.location
  os_type             = "Linux"
  sku_name            = "B1"
  worker_count        = 1
  tags                = local.tags
}
