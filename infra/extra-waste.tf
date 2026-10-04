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
