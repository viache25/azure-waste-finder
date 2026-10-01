# terraform test (run in infra/). The providers are mocked: no Azure login, nothing is created.

mock_provider "azurerm" {}
mock_provider "tls" {}

variables {
  prefix = "test"
}

run "smallest_skus" {
  command = plan

  assert {
    condition     = azurerm_linux_virtual_machine.stopped.size == "Standard_B1s"
    error_message = "The demo VM must use the smallest burstable size Standard_B1s."
  }

  assert {
    condition     = azurerm_linux_virtual_machine.stopped.os_disk[0].storage_account_type == "Standard_LRS"
    error_message = "The VM OS disk must be Standard HDD (Standard_LRS)."
  }

  assert {
    condition     = azurerm_managed_disk.orphaned.storage_account_type == "Standard_LRS" && azurerm_managed_disk.orphaned.disk_size_gb == 32
    error_message = "The orphaned disk must be a 32 GB Standard HDD (S4, the smallest Standard HDD tier)."
  }

  assert {
    condition     = azurerm_public_ip.orphaned.sku == "Standard" && azurerm_public_ip.orphaned.allocation_method == "Static"
    error_message = "The orphaned public IP must be one static Standard IP."
  }
}

run "required_tags" {
  command = plan

  assert {
    condition = alltrue([
      for tags in [
        azurerm_resource_group.demo.tags,
        azurerm_managed_disk.orphaned.tags,
        azurerm_public_ip.orphaned.tags,
        azurerm_virtual_network.demo.tags,
        azurerm_network_interface.vm.tags,
        azurerm_linux_virtual_machine.stopped.tags,
      ] : tags == tomap({ project = "azure-waste-finder", purpose = "waste-demo", managed_by = "terraform" })
    ])
    error_message = "Every taggable resource must carry the project, purpose and managed_by tags."
  }
}

run "vm_not_reachable" {
  command = plan

  assert {
    condition     = alltrue([for ip in azurerm_network_interface.vm.ip_configuration : ip.public_ip_address_id == null])
    error_message = "The VM NIC must not have a public IP."
  }

  assert {
    condition     = azurerm_linux_virtual_machine.stopped.disable_password_authentication
    error_message = "Password login must be disabled on the demo VM."
  }

  assert {
    condition     = azurerm_managed_disk.orphaned.public_network_access_enabled == false
    error_message = "The orphaned disk must not allow public network access."
  }
}

run "budget_needs_email" {
  command = plan

  variables {
    enable_budget = true
    alert_email   = null
  }

  assert {
    condition     = length(azurerm_consumption_budget_resource_group.safety) == 0
    error_message = "Without alert_email there is nobody to notify, so no budget is created."
  }
}

run "budget_enabled" {
  command = plan

  variables {
    enable_budget = true
    alert_email   = "owner@example.com"
  }

  assert {
    condition     = length(azurerm_consumption_budget_resource_group.safety) == 1
    error_message = "enable_budget = true with an alert_email must create the budget."
  }

  assert {
    condition     = azurerm_consumption_budget_resource_group.safety[0].amount == 5
    error_message = "The default budget is 5 per month."
  }

  assert {
    condition = alltrue([
      for n in azurerm_consumption_budget_resource_group.safety[0].notification : n.contact_emails == ["owner@example.com"]
    ])
    error_message = "Every budget notification must go to alert_email."
  }
}

run "budget_disabled" {
  command = plan

  variables {
    enable_budget = false
    alert_email   = "owner@example.com"
  }

  assert {
    condition     = length(azurerm_consumption_budget_resource_group.safety) == 0
    error_message = "enable_budget = false must not create a budget."
  }
}
