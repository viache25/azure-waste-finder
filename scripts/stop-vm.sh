#!/usr/bin/env bash
# Stop the demo VM WITHOUT deallocating it. Compute keeps being billed - that's the point.
set -euo pipefail
cd "$(dirname "$0")/../infra"
RG=$(terraform output -raw resource_group_name)
VM=$(terraform output -raw vm_name)
echo "Stopping $VM in $RG (not deallocating)..."
az vm stop --resource-group "$RG" --name "$VM"
az vm get-instance-view --resource-group "$RG" --name "$VM" \
  --query "instanceView.statuses[?starts_with(code,'PowerState/')].code" -o tsv
