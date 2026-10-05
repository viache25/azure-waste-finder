terraform {
  required_version = ">= 1.7" # terraform test with mock_provider

  required_providers {
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 3.10"
    }
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.7"
    }
  }
}

# Both providers use the `az login` of whoever applies this once (see README "Connect GitHub to Azure").
provider "azuread" {
  # null -> ARM_TENANT_ID or the tenant of the `az login` session.
  tenant_id = var.tenant_id
}

provider "azurerm" {
  features {}

  # null -> falls back to ARM_SUBSCRIPTION_ID or the `az login` default subscription.
  subscription_id = var.subscription_id

  # Only role assignments and one resource group: no resource provider needs registering.
  resource_provider_registrations = "none"
}
