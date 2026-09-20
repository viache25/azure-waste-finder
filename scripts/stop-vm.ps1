# Stop the demo VM WITHOUT deallocating it. Compute keeps being billed - that's the point.
$ErrorActionPreference = "Stop"
Push-Location (Join-Path $PSScriptRoot "..\infra")
try {
    $rg = terraform output -raw resource_group_name
    $vm = terraform output -raw vm_name
    Write-Host "Stopping $vm in $rg (not deallocating)..."
    az vm stop --resource-group $rg --name $vm
    az vm get-instance-view --resource-group $rg --name $vm `
        --query "instanceView.statuses[?starts_with(code,'PowerState/')].code" -o tsv
}
finally {
    Pop-Location
}
