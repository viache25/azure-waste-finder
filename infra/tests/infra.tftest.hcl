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
      for n in azurerm_consumption_budget_resource_group.safety[0].notification : n.contact_emails == tolist(["owner@example.com"])
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

run "extra_waste_off_by_default" {
  command = plan

  assert {
    condition     = length(azurerm_snapshot.old) == 0
    error_message = "Extra waste resources must be opt-in (enable_extra_waste defaults to false)."
  }

  assert {
    condition     = output.expected_findings.old_snapshot == null
    error_message = "Without extra waste there is no snapshot to find."
  }
}

run "extra_waste_snapshot" {
  command = plan

  variables {
    enable_extra_waste = true
  }

  # The disk ID is only known after apply; give it a fixed value at plan time to compare against.
  override_resource {
    target          = azurerm_managed_disk.orphaned
    override_during = plan
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-waste-demo-rg/providers/Microsoft.Compute/disks/test-orphaned-disk"
    }
  }

  assert {
    condition     = length(azurerm_snapshot.old) == 1
    error_message = "enable_extra_waste = true must create the old snapshot."
  }

  assert {
    condition     = azurerm_snapshot.old[0].create_option == "Copy" && azurerm_snapshot.old[0].source_uri == azurerm_managed_disk.orphaned.id
    error_message = "The snapshot must copy the orphaned disk."
  }

  assert {
    condition     = azurerm_snapshot.old[0].incremental_enabled
    error_message = "The snapshot must be incremental (billed by changed data only, the cheapest kind)."
  }

  assert {
    condition     = azurerm_snapshot.old[0].public_network_access_enabled == false && azurerm_snapshot.old[0].network_access_policy == "DenyAll"
    error_message = "The snapshot must not allow export over the internet."
  }

  assert {
    condition     = azurerm_snapshot.old[0].tags == tomap({ project = "azure-waste-finder", purpose = "waste-demo", managed_by = "terraform" })
    error_message = "The snapshot must carry the project, purpose and managed_by tags."
  }

  assert {
    condition     = output.expected_findings.old_snapshot == "test-old-snapshot"
    error_message = "expected_findings must list the snapshot when extra waste is enabled."
  }
}
