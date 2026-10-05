# None of these values is a secret: they only name the identity. The trust comes from the federated credentials.

locals {
  github_variables = tomap(merge(
    {
      AZURE_CLIENT_ID       = azuread_application.github.client_id
      AZURE_TENANT_ID       = data.azurerm_subscription.current.tenant_id
      AZURE_SUBSCRIPTION_ID = data.azurerm_subscription.current.subscription_id
    },
    var.enable_e2e ? { AZURE_E2E_RESOURCE_GROUP = azurerm_resource_group.e2e[0].name } : {},
  ))
}

output "client_id" {
  description = "Application (client) ID -> repo variable AZURE_CLIENT_ID."
  value       = azuread_application.github.client_id
}

output "tenant_id" {
  description = "Entra tenant ID -> repo variable AZURE_TENANT_ID."
  value       = data.azurerm_subscription.current.tenant_id
}

output "subscription_id" {
  description = "Subscription ID -> repo variable AZURE_SUBSCRIPTION_ID."
  value       = data.azurerm_subscription.current.subscription_id
}

output "federated_subjects" {
  description = "OIDC subjects that may log in as this identity."
  value       = tomap({ for key, credential in azuread_application_federated_identity_credential.github : key => credential.subject })
}

output "e2e_resource_group" {
  description = "Resource group for e2e.yml (null unless enable_e2e = true) -> repo variable AZURE_E2E_RESOURCE_GROUP."
  value       = one(azurerm_resource_group.e2e[*].name)
}

output "github_variables" {
  description = "Repository variables the Azure workflows read."
  value       = local.github_variables
}

output "gh_variable_commands" {
  description = "The gh commands that set the repository variables."
  value = join("\n", [
    for name, value in local.github_variables : "gh variable set ${name} --repo ${var.github_repository} --body '${value}'"
  ])
}
