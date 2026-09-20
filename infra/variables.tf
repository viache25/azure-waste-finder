variable "subscription_id" {
  description = "Azure subscription ID. Leave null to use ARM_SUBSCRIPTION_ID / az login default."
  type        = string
  default     = null
}

variable "prefix" {
  description = "Name prefix for all resources."
  type        = string
  default     = "awf"
}

variable "location" {
  description = "Azure region. Change it if the VM size is not available there."
  type        = string
  default     = "westeurope"
}

variable "vm_size" {
  description = "Size of the demo VM. Smallest burstable size keeps the bill tiny."
  type        = string
  default     = "Standard_B1s"
}

variable "enable_budget" {
  description = "Create a monthly budget alert on the resource group."
  type        = bool
  default     = true
}

variable "budget_amount" {
  description = "Monthly budget in the billing currency."
  type        = number
  default     = 5
}

variable "alert_email" {
  description = "Where budget alerts are sent."
  type        = string
  default     = null
}
