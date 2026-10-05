locals {
  tags = {
    project    = "azure-waste-finder"
    purpose    = "waste-demo"
    managed_by = "terraform"
  }

  # Everything goes into the group created here, or into an existing one (var.resource_group_name, used by e2e.yml).
  resource_group_name = var.resource_group_name == null ? azurerm_resource_group.demo[0].name : data.azurerm_resource_group.existing[0].name
  resource_group_id   = var.resource_group_name == null ? azurerm_resource_group.demo[0].id : data.azurerm_resource_group.existing[0].id
  location            = var.resource_group_name == null ? azurerm_resource_group.demo[0].location : data.azurerm_resource_group.existing[0].location
}

resource "azurerm_resource_group" "demo" {
  count = var.resource_group_name == null ? 1 : 0

  name     = "${var.prefix}-waste-demo-rg"
  location = var.location
  tags     = local.tags
}

# Before resource_group_name existed the group had no count; keeps existing state without a re-create.
moved {
  from = azurerm_resource_group.demo
  to   = azurerm_resource_group.demo[0]
}

# The live end-to-end test may only write to one prepared group (infra/github-oidc, enable_e2e).
data "azurerm_resource_group" "existing" {
  count = var.resource_group_name == null ? 0 : 1

  name = var.resource_group_name
}

# Safety net: e-mail when the resource group reaches 50% / 100% of the budget.
resource "azurerm_consumption_budget_resource_group" "safety" {
  count = var.enable_budget && var.alert_email != null ? 1 : 0

  name              = "${var.prefix}-budget"
  resource_group_id = local.resource_group_id
  amount            = var.budget_amount
  time_grain        = "Monthly"

  time_period {
    start_date = formatdate("YYYY-MM-01'T00:00:00Z'", timestamp())
  }

  notification {
    enabled        = true
    operator       = "GreaterThanOrEqualTo"
    threshold      = 50
    threshold_type = "Actual"
    contact_emails = [var.alert_email]
  }

  notification {
    enabled        = true
    operator       = "GreaterThanOrEqualTo"
    threshold      = 100
    threshold_type = "Forecasted"
    contact_emails = [var.alert_email]
  }

  lifecycle {
    # timestamp() changes on every plan; the start date only matters on creation.
    ignore_changes = [time_period]
  }
}
