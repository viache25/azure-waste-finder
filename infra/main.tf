locals {
  tags = {
    project    = "azure-waste-finder"
    purpose    = "waste-demo"
    managed_by = "terraform"
  }
}

resource "azurerm_resource_group" "demo" {
  name     = "${var.prefix}-waste-demo-rg"
  location = var.location
  tags     = local.tags
}

# Safety net: e-mail when the resource group reaches 50% / 100% of the budget.
resource "azurerm_consumption_budget_resource_group" "safety" {
  count = var.enable_budget && var.alert_email != null ? 1 : 0

  name              = "${var.prefix}-budget"
  resource_group_id = azurerm_resource_group.demo.id
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
