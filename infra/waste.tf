# Three typical kinds of cloud waste. Each one is billed although nobody uses it.

# 1) Managed disk that is not attached to any VM (e.g. left over after a VM was deleted).
resource "azurerm_managed_disk" "orphaned" {
  name                 = "${var.prefix}-orphaned-disk"
  resource_group_name  = azurerm_resource_group.demo.name
  location             = azurerm_resource_group.demo.location
  storage_account_type = "Standard_LRS"
  create_option        = "Empty"
  disk_size_gb         = 32
  tags                 = local.tags
}

# 2) Public IP that is not associated with anything. Standard SKU is billed per hour.
resource "azurerm_public_ip" "orphaned" {
  name                = "${var.prefix}-orphaned-pip"
  resource_group_name = azurerm_resource_group.demo.name
  location            = azurerm_resource_group.demo.location
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = local.tags
}

# 3) VM that will be "stopped" from inside the OS / with `az vm stop` but NOT deallocated.
#    Terraform can't leave a VM in that state, so scripts/stop-vm.* does it after apply.
resource "azurerm_virtual_network" "demo" {
  name                = "${var.prefix}-vnet"
  resource_group_name = azurerm_resource_group.demo.name
  location            = azurerm_resource_group.demo.location
  address_space       = ["10.10.0.0/16"]
  tags                = local.tags
}

resource "azurerm_subnet" "demo" {
  name                 = "default"
  resource_group_name  = azurerm_resource_group.demo.name
  virtual_network_name = azurerm_virtual_network.demo.name
  address_prefixes     = ["10.10.1.0/24"]
}

# No public IP on the NIC: the VM is never reachable from the internet.
resource "azurerm_network_interface" "vm" {
  name                = "${var.prefix}-vm-nic"
  resource_group_name = azurerm_resource_group.demo.name
  location            = azurerm_resource_group.demo.location
  tags                = local.tags

  ip_configuration {
    name                          = "internal"
    subnet_id                     = azurerm_subnet.demo.id
    private_ip_address_allocation = "Dynamic"
  }
}

# Throwaway SSH key, only needed because Azure requires a login method.
# It lives in the local state file, which is git-ignored.
resource "tls_private_key" "vm" {
  algorithm = "ED25519"
}

resource "azurerm_linux_virtual_machine" "stopped" {
  name                            = "${var.prefix}-stopped-vm"
  resource_group_name             = azurerm_resource_group.demo.name
  location                        = azurerm_resource_group.demo.location
  size                            = var.vm_size
  admin_username                  = "azureuser"
  disable_password_authentication = true
  network_interface_ids           = [azurerm_network_interface.vm.id]
  tags                            = local.tags

  admin_ssh_key {
    username   = "azureuser"
    public_key = tls_private_key.vm.public_key_openssh
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts-gen2"
    version   = "latest"
  }
}
