variable "subscription_id" {
  description = "Subscription the identity may read (and where the E2E resource group lives). Leave null to use ARM_SUBSCRIPTION_ID / az login default."
  type        = string
  default     = null
}

variable "tenant_id" {
  description = "Entra tenant for the app registration. Leave null to use ARM_TENANT_ID / the az login tenant."
  type        = string
  default     = null
}

variable "github_repository" {
  description = "GitHub repository (owner/name) whose workflows may log in as this identity."
  type        = string
  default     = "viache25/azure-waste-finder"

  validation {
    condition     = can(regex("^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$", var.github_repository))
    error_message = "github_repository must look like owner/name."
  }
}

variable "github_branch" {
  description = "Branch whose workflow runs (scheduled FinOps check, manual runs) may log in; subject repo:<repo>:ref:refs/heads/<branch>."
  type        = string
  default     = "main"
}

variable "github_environment" {
  description = "GitHub environment of the live end-to-end test (e2e.yml); subject repo:<repo>:environment:<name>."
  type        = string
  default     = "azure-e2e"
}

variable "app_display_name" {
  description = "Display name of the Entra app registration."
  type        = string
  default     = "github-azure-waste-finder"
}

variable "enable_e2e" {
  description = "Create the resource group for the live end-to-end test (e2e.yml) and give the identity Contributor on that group only."
  type        = bool
  default     = false
}

variable "e2e_resource_group_name" {
  description = "Name of the resource group e2e.yml deploys the demo waste into (only with enable_e2e = true)."
  type        = string
  default     = "awf-e2e-rg"
}

variable "location" {
  description = "Region of the E2E resource group."
  type        = string
  default     = "westeurope"
}
