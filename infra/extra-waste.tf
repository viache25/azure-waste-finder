# Opt-in waste for the newer rules (enable_extra_waste = true). Smallest SKUs; the README lists the cost per hour.

# Snapshot of the orphaned disk. Snapshots bill per GB-month of used data; the source disk is empty,
# so this costs next to nothing. waste-finder reports it once it is older than snapshot_min_age_days
# (default 30); run with --snapshot-min-age 0 to see it right after `terraform apply`.
resource "azurerm_snapshot" "old" {
  count = var.enable_extra_waste ? 1 : 0

  name                = "${var.prefix}-old-snapshot"
  resource_group_name = local.resource_group_name
  location            = local.location
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
  resource_group_name = local.resource_group_name
  location            = local.location
  os_type             = "Linux"
  sku_name            = "B1"
  worker_count        = 1
  tags                = local.tags
}

# Standard load balancer with an empty backend pool and no rules. Internal (private frontend in the demo
# subnet), so no public IP is needed. Without rules Azure charges nothing per hour: waste-finder reports
# it as a free "info" finding. Adding a load-balancing rule would make it bill (~0.022 €/h).
resource "azurerm_lb" "idle" {
  count = var.enable_extra_waste ? 1 : 0

  name                = "${var.prefix}-idle-lb"
  resource_group_name = local.resource_group_name
  location            = local.location
  sku                 = "Standard"
  tags                = local.tags

  frontend_ip_configuration {
    name                          = "internal"
    subnet_id                     = azurerm_subnet.demo.id
    private_ip_address_allocation = "Dynamic"
  }
}

resource "azurerm_lb_backend_address_pool" "idle" {
  count = var.enable_extra_waste ? 1 : 0

  name            = "empty"
  loadbalancer_id = azurerm_lb.idle[0].id
}

# Free clean-up findings ("Aufräumen (kostenlos)"): none of these costs anything.

# Network interface without a VM, e.g. left behind after a VM was deleted. Private IP only.
resource "azurerm_network_interface" "orphaned" {
  count = var.enable_extra_waste ? 1 : 0

  name                = "${var.prefix}-orphaned-nic"
  resource_group_name = local.resource_group_name
  location            = local.location
  tags                = local.tags

  ip_configuration {
    name                          = "internal"
    subnet_id                     = azurerm_subnet.demo.id
    private_ip_address_allocation = "Dynamic"
  }
}

# Network security group that is associated with neither a subnet nor a NIC (and has no custom rules).
resource "azurerm_network_security_group" "unattached" {
  count = var.enable_extra_waste ? 1 : 0

  name                = "${var.prefix}-unattached-nsg"
  resource_group_name = local.resource_group_name
  location            = local.location
  tags                = local.tags
}

# Resource group without any resource.
resource "azurerm_resource_group" "empty" {
  count = var.enable_extra_waste ? 1 : 0

  name     = "${var.prefix}-empty-rg"
  location = var.location
  tags     = local.tags
}
