terraform {
  required_version = ">= 1.6"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }
}

provider "azurerm" {
  features {
    resource_group {
      # Lets `terraform destroy` clean up even if something extra landed in the RG.
      prevent_deletion_if_contains_resources = false
    }
  }

  # null -> falls back to ARM_SUBSCRIPTION_ID or the `az login` default subscription.
  subscription_id = var.subscription_id
}
