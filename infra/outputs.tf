output "resource_group_name" {
  value = azurerm_resource_group.demo.name
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
  }
}
