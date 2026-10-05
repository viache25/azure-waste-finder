# Three typical kinds of cloud waste. Each one is billed although nobody uses it.

# 1) Managed disk that is not attached to any VM (e.g. left over after a VM was deleted).
resource "azurerm_managed_disk" "orphaned" {
  #checkov:skip=CKV_AZURE_93:Empty throwaway demo disk; platform-managed keys are enough, a CMK needs a paid Key Vault
  name                 = "${var.prefix}-orphaned-disk"
  resource_group_name  = local.resource_group_name
  location             = local.location
  storage_account_type = "Standard_LRS"
  create_option        = "Empty"
  disk_size_gb         = 32
  tags                 = local.tags

  # No SAS export / import over the internet.
  public_network_access_enabled = false
  network_access_policy         = "DenyAll"
}

# 2) Public IP that is not associated with anything. Standard SKU is billed per hour.
resource "azurerm_public_ip" "orphaned" {
  name                = "${var.prefix}-orphaned-pip"
  resource_group_name = local.resource_group_name
  location            = local.location
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = local.tags
}

# 3) VM that will be "stopped" from inside the OS / with `az vm stop` but NOT deallocated.
#    Terraform can't leave a VM in that state, so scripts/stop-vm.* does it after apply.
resource "azurerm_virtual_network" "demo" {
  name                = "${var.prefix}-vnet"
  resource_group_name = local.resource_group_name
  location            = local.location
  address_space       = ["10.10.0.0/16"]
  tags                = local.tags
}

resource "azurerm_subnet" "demo" {
  #checkov:skip=CKV2_AZURE_31:The only NIC belongs to the demo VM, which has no public IP; nothing inbound to filter
  name                 = "default"
  resource_group_name  = local.resource_group_name
  virtual_network_name = azurerm_virtual_network.demo.name
  address_prefixes     = ["10.10.1.0/24"]
}

# No public IP on the NIC: the VM is never reachable from the internet.
resource "azurerm_network_interface" "vm" {
  name                = "${var.prefix}-vm-nic"
  resource_group_name = local.resource_group_name
  location            = local.location
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
  #checkov:skip=CKV_AZURE_50:No extensions are declared; the VM only exists to be stopped
  name                            = "${var.prefix}-stopped-vm"
  resource_group_name             = local.resource_group_name
  location                        = local.location
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
