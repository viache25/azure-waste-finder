# terraform test (run in infra/github-oidc/). The providers are mocked: no Azure login, nothing is created.
# Computed IDs get fixed, well-formed values at plan time (override_during = plan), because downstream
# resources validate their format.

mock_provider "azuread" {
  override_during = plan

  mock_data "azuread_client_config" {
    defaults = {
      object_id = "11111111-1111-1111-1111-111111111111"
      tenant_id = "22222222-2222-2222-2222-222222222222"
      client_id = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"
    }
  }

  mock_resource "azuread_application" {
    defaults = {
      id        = "/applications/33333333-3333-3333-3333-333333333333"
      object_id = "33333333-3333-3333-3333-333333333333"
      client_id = "44444444-4444-4444-4444-444444444444"
    }
  }

  mock_resource "azuread_service_principal" {
    defaults = {
      id        = "/servicePrincipals/55555555-5555-5555-5555-555555555555"
      object_id = "55555555-5555-5555-5555-555555555555"
    }
  }
}

mock_provider "azurerm" {
  override_during = plan

  mock_data "azurerm_subscription" {
    defaults = {
      id              = "/subscriptions/00000000-0000-0000-0000-000000000000"
      subscription_id = "00000000-0000-0000-0000-000000000000"
      tenant_id       = "22222222-2222-2222-2222-222222222222"
    }
  }

  mock_resource "azurerm_resource_group" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/awf-e2e-rg"
    }
  }
}

run "federated_credentials" {
  command = plan

  assert {
    condition     = length(azuread_application_federated_identity_credential.github) == 2
    error_message = "Exactly two federated credentials: the main branch and the azure-e2e environment."
  }

  assert {
    condition     = azuread_application_federated_identity_credential.github["branch"].subject == "repo:viache25/azure-waste-finder:ref:refs/heads/main"
    error_message = "The branch credential must trust workflow runs on main of viache25/azure-waste-finder only."
  }

  assert {
    condition     = azuread_application_federated_identity_credential.github["environment"].subject == "repo:viache25/azure-waste-finder:environment:azure-e2e"
    error_message = "The environment credential must trust jobs in the azure-e2e environment only."
  }

  assert {
    condition = alltrue([
      for c in azuread_application_federated_identity_credential.github :
      c.issuer == "https://token.actions.githubusercontent.com" && c.audiences == tolist(["api://AzureADTokenExchange"])
    ])
    error_message = "Federated credentials must trust GitHub's OIDC issuer with the audience azure/login requests."
  }

  assert {
    condition = alltrue([
      for c in azuread_application_federated_identity_credential.github :
      c.application_id == "/applications/33333333-3333-3333-3333-333333333333"
    ])
    error_message = "The federated credentials must belong to the app registration."
  }

  assert {
    condition     = azuread_service_principal.github.client_id == "44444444-4444-4444-4444-444444444444"
    error_message = "The service principal must be the one of the app registration."
  }

  assert {
    condition     = azuread_application.github.sign_in_audience == "AzureADMyOrg" && length(azuread_application.github.password) == 0
    error_message = "Single-tenant app without a client secret: login only through the federated credentials."
  }

  assert {
    condition     = output.federated_subjects == tomap({ branch = "repo:viache25/azure-waste-finder:ref:refs/heads/main", environment = "repo:viache25/azure-waste-finder:environment:azure-e2e" })
    error_message = "federated_subjects must list both subjects."
  }
}

run "read_only_on_the_subscription" {
  command = plan

  assert {
    condition     = toset([for a in azurerm_role_assignment.subscription : a.role_definition_name]) == toset(["Reader", "Cost Management Reader"])
    error_message = "On the subscription the identity gets exactly Reader and Cost Management Reader."
  }

  assert {
    condition = alltrue([
      for a in azurerm_role_assignment.subscription :
      a.scope == "/subscriptions/00000000-0000-0000-0000-000000000000" && a.principal_id == "55555555-5555-5555-5555-555555555555" && a.principal_type == "ServicePrincipal"
    ])
    error_message = "The subscription roles must be assigned to the service principal on the subscription scope."
  }
}

run "e2e_off_by_default" {
  command = plan

  assert {
    condition     = length(azurerm_resource_group.e2e) == 0 && length(azurerm_role_assignment.e2e_contributor) == 0
    error_message = "Without enable_e2e there is no E2E resource group and no write permission at all."
  }

  assert {
    condition     = output.e2e_resource_group == null && !contains(keys(output.github_variables), "AZURE_E2E_RESOURCE_GROUP")
    error_message = "Without enable_e2e no E2E resource group is output."
  }
}

run "e2e_contributor_on_its_group_only" {
  command = plan

  variables {
    enable_e2e = true
  }

  assert {
    condition     = length(azurerm_resource_group.e2e) == 1 && azurerm_resource_group.e2e[0].name == "awf-e2e-rg" && azurerm_resource_group.e2e[0].location == "westeurope"
    error_message = "enable_e2e = true must create the E2E resource group awf-e2e-rg."
  }

  assert {
    condition     = azurerm_resource_group.e2e[0].tags["waste-finder:ignore"] == "true" && azurerm_resource_group.e2e[0].tags["project"] == "azure-waste-finder"
    error_message = "The E2E group carries the project tag and waste-finder:ignore, so the weekly check skips it while empty."
  }

  assert {
    condition     = length(azurerm_role_assignment.e2e_contributor) == 1 && azurerm_role_assignment.e2e_contributor[0].role_definition_name == "Contributor"
    error_message = "enable_e2e = true must assign Contributor for the E2E test."
  }

  assert {
    condition     = azurerm_role_assignment.e2e_contributor[0].scope == "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/awf-e2e-rg"
    error_message = "Contributor must be scoped to the E2E resource group, never to the subscription."
  }

  assert {
    condition     = azurerm_role_assignment.e2e_contributor[0].principal_id == "55555555-5555-5555-5555-555555555555"
    error_message = "Contributor goes to the service principal."
  }

  assert {
    condition     = toset([for a in azurerm_role_assignment.subscription : a.role_definition_name]) == toset(["Reader", "Cost Management Reader"])
    error_message = "enable_e2e must not widen the subscription roles."
  }

  assert {
    condition     = output.e2e_resource_group == "awf-e2e-rg" && output.github_variables["AZURE_E2E_RESOURCE_GROUP"] == "awf-e2e-rg"
    error_message = "The E2E resource group must be output as AZURE_E2E_RESOURCE_GROUP."
  }
}

run "github_variables" {
  command = plan

  assert {
    condition = output.github_variables == tomap({
      AZURE_CLIENT_ID       = "44444444-4444-4444-4444-444444444444"
      AZURE_TENANT_ID       = "22222222-2222-2222-2222-222222222222"
      AZURE_SUBSCRIPTION_ID = "00000000-0000-0000-0000-000000000000"
    })
    error_message = "github_variables must hold client, tenant and subscription ID."
  }

  assert {
    condition     = strcontains(output.gh_variable_commands, "gh variable set AZURE_CLIENT_ID --repo viache25/azure-waste-finder --body '44444444-4444-4444-4444-444444444444'")
    error_message = "gh_variable_commands must set AZURE_CLIENT_ID on the repository."
  }

  assert {
    condition     = length(split("\n", output.gh_variable_commands)) == 3
    error_message = "Without enable_e2e three variables are set."
  }
}

run "other_repository" {
  command = plan

  variables {
    github_repository  = "contoso/finops"
    github_branch      = "release"
    github_environment = "prod-e2e"
  }

  assert {
    condition     = azuread_application_federated_identity_credential.github["branch"].subject == "repo:contoso/finops:ref:refs/heads/release"
    error_message = "The branch subject must follow github_repository and github_branch."
  }

  assert {
    condition     = azuread_application_federated_identity_credential.github["environment"].subject == "repo:contoso/finops:environment:prod-e2e"
    error_message = "The environment subject must follow github_repository and github_environment."
  }
}

run "repository_must_be_owner_slash_name" {
  command = plan

  variables {
    github_repository = "azure-waste-finder"
  }

  expect_failures = [var.github_repository]
}
