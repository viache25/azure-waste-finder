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
        azurerm_resource_group.demo[0].tags,
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

  assert {
    condition     = length(azurerm_service_plan.empty) == 0 && output.expected_findings.empty_app_service_plan == null
    error_message = "The empty App Service plan must be opt-in (enable_extra_waste)."
  }

  assert {
    condition     = length(azurerm_lb.idle) == 0 && length(azurerm_lb_backend_address_pool.idle) == 0 && output.expected_findings.idle_load_balancer == null
    error_message = "The idle load balancer must be opt-in (enable_extra_waste)."
  }

  assert {
    condition     = length(azurerm_network_interface.orphaned) + length(azurerm_network_security_group.unattached) + length(azurerm_resource_group.empty) == 0
    error_message = "The clean-up resources (orphaned NIC, unattached NSG, empty resource group) must be opt-in."
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

run "extra_waste_app_service_plan" {
  command = plan

  variables {
    enable_extra_waste = true
  }

  assert {
    condition     = length(azurerm_service_plan.empty) == 1
    error_message = "enable_extra_waste = true must create the empty App Service plan."
  }

  assert {
    condition     = azurerm_service_plan.empty[0].sku_name == "B1" && azurerm_service_plan.empty[0].os_type == "Linux" && azurerm_service_plan.empty[0].worker_count == 1
    error_message = "The empty plan must be the cheapest paid plan: B1 Linux with one instance."
  }

  assert {
    condition     = azurerm_service_plan.empty[0].tags == tomap({ project = "azure-waste-finder", purpose = "waste-demo", managed_by = "terraform" })
    error_message = "The App Service plan must carry the project, purpose and managed_by tags."
  }

  assert {
    condition     = output.expected_findings.empty_app_service_plan == "test-empty-plan"
    error_message = "expected_findings must list the plan when extra waste is enabled."
  }
}

run "extra_waste_idle_load_balancer" {
  command = plan

  variables {
    enable_extra_waste = true
  }

  assert {
    condition     = length(azurerm_lb.idle) == 1 && azurerm_lb.idle[0].sku == "Standard"
    error_message = "enable_extra_waste = true must create one Standard load balancer."
  }

  assert {
    condition     = alltrue([for fe in azurerm_lb.idle[0].frontend_ip_configuration : fe.public_ip_address_id == null && fe.private_ip_address_allocation == "Dynamic"])
    error_message = "The idle load balancer must be internal: a private frontend and no public IP (which would bill)."
  }

  assert {
    condition     = length(azurerm_lb_backend_address_pool.idle) == 1
    error_message = "The idle load balancer gets one backend pool, and it stays empty."
  }

  assert {
    condition     = azurerm_lb.idle[0].tags == tomap({ project = "azure-waste-finder", purpose = "waste-demo", managed_by = "terraform" })
    error_message = "The load balancer must carry the project, purpose and managed_by tags."
  }

  assert {
    condition     = output.expected_findings.idle_load_balancer == "test-idle-lb"
    error_message = "expected_findings must list the load balancer when extra waste is enabled."
  }
}

run "extra_waste_cleanup_findings" {
  command = plan

  variables {
    enable_extra_waste = true
  }

  assert {
    condition     = length(azurerm_network_interface.orphaned) == 1 && alltrue([for ip in azurerm_network_interface.orphaned[0].ip_configuration : ip.public_ip_address_id == null])
    error_message = "enable_extra_waste = true must create one orphaned NIC, without a public IP."
  }

  assert {
    condition     = length(azurerm_network_security_group.unattached) == 1
    error_message = "enable_extra_waste = true must create the unattached NSG."
  }

  assert {
    condition     = length(azurerm_resource_group.empty) == 1 && azurerm_resource_group.empty[0].name == "test-empty-rg"
    error_message = "enable_extra_waste = true must create the empty resource group."
  }

  assert {
    condition = alltrue([
      for tags in [
        azurerm_network_interface.orphaned[0].tags,
        azurerm_network_security_group.unattached[0].tags,
        azurerm_resource_group.empty[0].tags,
      ] : tags == tomap({ project = "azure-waste-finder", purpose = "waste-demo", managed_by = "terraform" })
    ])
    error_message = "The clean-up resources must carry the project, purpose and managed_by tags."
  }

  assert {
    condition     = output.expected_findings.orphaned_nic == "test-orphaned-nic" && output.expected_findings.unattached_nsg == "test-unattached-nsg" && output.expected_findings.empty_resource_group == "test-empty-rg"
    error_message = "expected_findings must list the clean-up resources when extra waste is enabled."
  }
}

run "own_resource_group_by_default" {
  command = plan

  assert {
    condition     = length(azurerm_resource_group.demo) == 1 && length(data.azurerm_resource_group.existing) == 0
    error_message = "Without resource_group_name the demo creates its own resource group."
  }

  assert {
    condition     = azurerm_resource_group.demo[0].name == "test-waste-demo-rg" && output.resource_group_name == "test-waste-demo-rg"
    error_message = "The own resource group is named <prefix>-waste-demo-rg."
  }

  assert {
    condition     = azurerm_managed_disk.orphaned.resource_group_name == "test-waste-demo-rg" && azurerm_linux_virtual_machine.stopped.location == "westeurope"
    error_message = "The waste goes into the own resource group, in var.location."
  }
}

# e2e.yml: deploy into the prepared group from infra/github-oidc (enable_e2e), where the identity has Contributor.
run "existing_resource_group" {
  command = plan

  variables {
    prefix              = "e2e-123-1"
    resource_group_name = "awf-e2e-rg"
    enable_budget       = false
  }

  override_data {
    target = data.azurerm_resource_group.existing[0]
    values = {
      id       = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/awf-e2e-rg"
      location = "northeurope"
    }
  }

  assert {
    condition     = length(azurerm_resource_group.demo) == 0
    error_message = "With resource_group_name no resource group is created (the E2E identity could not create one)."
  }

  assert {
    condition = alltrue([
      for rg in [
        azurerm_managed_disk.orphaned.resource_group_name,
        azurerm_public_ip.orphaned.resource_group_name,
        azurerm_virtual_network.demo.resource_group_name,
        azurerm_subnet.demo.resource_group_name,
        azurerm_network_interface.vm.resource_group_name,
        azurerm_linux_virtual_machine.stopped.resource_group_name,
      ] : rg == "awf-e2e-rg"
    ])
    error_message = "Every waste resource must go into the existing resource group."
  }

  assert {
    condition     = azurerm_managed_disk.orphaned.location == "northeurope" && azurerm_linux_virtual_machine.stopped.location == "northeurope"
    error_message = "Resources take the location of the existing group."
  }

  assert {
    condition     = output.resource_group_name == "awf-e2e-rg" && output.expected_findings.stopped_vm == "e2e-123-1-stopped-vm"
    error_message = "Outputs must name the existing group and the prefixed resources."
  }

  assert {
    condition     = output.expected_findings.unattached_disk == "e2e-123-1-orphaned-disk" && output.expected_findings.orphaned_ip == "e2e-123-1-orphaned-pip"
    error_message = "The unique prefix must reach the names of the three base waste resources."
  }

  assert {
    condition     = length(azurerm_consumption_budget_resource_group.safety) == 0
    error_message = "The E2E run creates no budget."
  }
}

run "workbook_off_by_default" {
  command = plan

  assert {
    condition     = length(azurerm_application_insights_workbook.waste_finder) == 0 && output.workbook_id == null
    error_message = "The workbook must be opt-in (enable_workbook defaults to false)."
  }
}

run "workbook_enabled" {
  command = plan

  variables {
    enable_workbook = true
  }

  assert {
    condition     = length(azurerm_application_insights_workbook.waste_finder) == 1
    error_message = "enable_workbook = true must create the workbook."
  }

  assert {
    condition     = azurerm_application_insights_workbook.waste_finder[0].name == uuidv5("url", "https://github.com/viache25/azure-waste-finder/workbook/test") && can(regex("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", azurerm_application_insights_workbook.waste_finder[0].name))
    error_message = "The workbook name must be a GUID that is stable per prefix."
  }

  assert {
    condition     = azurerm_application_insights_workbook.waste_finder[0].display_name == "Azure Waste Finder (test)" && azurerm_application_insights_workbook.waste_finder[0].category == "workbook" && azurerm_application_insights_workbook.waste_finder[0].source_id == "azure monitor"
    error_message = "The workbook must be a shared Azure Monitor workbook named after the prefix."
  }

  assert {
    condition     = azurerm_application_insights_workbook.waste_finder[0].data_json == file("${path.module}/../workbooks/waste-finder.workbook.json")
    error_message = "The workbook must deploy the generated workbooks/waste-finder.workbook.json unchanged."
  }

  assert {
    condition     = jsondecode(azurerm_application_insights_workbook.waste_finder[0].data_json).version == "Notebook/1.0"
    error_message = "data_json must be a workbook (Notebook/1.0)."
  }

  assert {
    condition = alltrue([
      for item in jsondecode(azurerm_application_insights_workbook.waste_finder[0].data_json).items :
      item.content.queryType == 1 && item.content.resourceType == "microsoft.resourcegraph/resources" if item.type == 3
    ]) && length([for item in jsondecode(azurerm_application_insights_workbook.waste_finder[0].data_json).items : item if item.type == 3]) >= 11
    error_message = "Every workbook query must use the Resource Graph data source, one per rule."
  }

  assert {
    condition     = azurerm_application_insights_workbook.waste_finder[0].resource_group_name == "test-waste-demo-rg" && azurerm_application_insights_workbook.waste_finder[0].location == "westeurope"
    error_message = "The workbook goes into the demo resource group, in var.location."
  }

  assert {
    condition     = azurerm_application_insights_workbook.waste_finder[0].tags == tomap({ project = "azure-waste-finder", purpose = "waste-demo", managed_by = "terraform" })
    error_message = "The workbook must carry the project, purpose and managed_by tags."
  }
}
