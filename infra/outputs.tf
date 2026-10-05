output "resource_group_name" {
  value = local.resource_group_name
}

output "vm_name" {
  value = azurerm_linux_virtual_machine.stopped.name
}

output "expected_findings" {
  description = "What waste-finder should report after scripts/stop-vm has run."

  value = {
    unattached_disk = azurerm_managed_disk.orphaned.name
    stopped_vm      = azurerm_linux_virtual_machine.stopped.name
    orphaned_ip     = azurerm_public_ip.orphaned.name
    # Opt-in (enable_extra_waste); null when disabled.
    old_snapshot           = one(azurerm_snapshot.old[*].name)
    empty_app_service_plan = one(azurerm_service_plan.empty[*].name)
    idle_load_balancer     = one(azurerm_lb.idle[*].name)
    orphaned_nic           = one(azurerm_network_interface.orphaned[*].name)
    unattached_nsg         = one(azurerm_network_security_group.unattached[*].name)
    empty_resource_group   = one(azurerm_resource_group.empty[*].name)
  }
}
