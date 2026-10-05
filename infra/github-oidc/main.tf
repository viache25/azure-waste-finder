# OIDC identity for GitHub Actions: an Entra app registration whose federated credentials trust tokens that
# GitHub issues to this repository's workflows. No client secret exists; azure/login exchanges the workflow's
# OIDC token for an Azure token. Applied once by the owner (README "Connect GitHub to Azure").

data "azuread_client_config" "current" {}

data "azurerm_subscription" "current" {}

locals {
  tags = {
    project    = "azure-waste-finder"
    purpose    = "github-oidc"
    managed_by = "terraform"
  }

  # GitHub's OIDC issuer and the audience azure/login requests.
  github_issuer = "https://token.actions.githubusercontent.com"
  audience      = "api://AzureADTokenExchange"

  # One federated credential per workflow context that may log in.
  federated_subjects = {
    # Jobs without an environment on the branch: the scheduled FinOps check (finops-check.yml).
    branch = "repo:${var.github_repository}:ref:refs/heads/${var.github_branch}"
    # Jobs with `environment: azure-e2e`: the manual live end-to-end test (e2e.yml).
    environment = "repo:${var.github_repository}:environment:${var.github_environment}"
  }

  # Read-only on the whole subscription: Resource Graph needs Reader, --cost-source actual Cost Management Reader.
  subscription_roles = toset(["Reader", "Cost Management Reader"])
}

resource "azuread_application" "github" {
  display_name     = var.app_display_name
  owners           = [data.azuread_client_config.current.object_id]
  sign_in_audience = "AzureADMyOrg"
  notes            = "GitHub Actions OIDC login for ${var.github_repository} (azure-waste-finder). Managed by Terraform in infra/github-oidc."
}

resource "azuread_service_principal" "github" {
  client_id = azuread_application.github.client_id
  owners    = [data.azuread_client_config.current.object_id]
}

resource "azuread_application_federated_identity_credential" "github" {
  for_each = local.federated_subjects

  application_id = azuread_application.github.id
  display_name   = "github-${each.key}"
  description    = "GitHub Actions: ${each.value}"
  audiences      = [local.audience]
  issuer         = local.github_issuer
  subject        = each.value
}

resource "azurerm_role_assignment" "subscription" {
  for_each = local.subscription_roles

  scope                = data.azurerm_subscription.current.id
  role_definition_name = each.value
  principal_id         = azuread_service_principal.github.object_id
  principal_type       = "ServicePrincipal"
  description          = "azure-waste-finder: GitHub Actions (${var.github_repository}) reads the subscription"
}

# Opt-in (enable_e2e): the live end-to-end test deploys the demo waste into this group and destroys it again.
# Contributor on this group only, so the identity cannot change anything else in the subscription. The tag
# keeps the group, which is empty between E2E runs, out of the weekly FinOps report.
resource "azurerm_resource_group" "e2e" {
  count = var.enable_e2e ? 1 : 0

  name     = var.e2e_resource_group_name
  location = var.location
  tags     = merge(local.tags, { purpose = "e2e-test", "waste-finder:ignore" = "true" })
}

resource "azurerm_role_assignment" "e2e_contributor" {
  count = var.enable_e2e ? 1 : 0

  scope                = azurerm_resource_group.e2e[0].id
  role_definition_name = "Contributor"
  principal_id         = azuread_service_principal.github.object_id
  principal_type       = "ServicePrincipal"
  description          = "azure-waste-finder: e2e.yml creates and destroys the demo waste in this group"
}
