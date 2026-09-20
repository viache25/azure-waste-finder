# Azure Waste Finder

A mini "Kostencheck" for Azure. Terraform deploys a deliberately wasteful environment (unattached disk, stopped-but-not-deallocated VM, orphaned public IP). A Python CLI finds the waste via Azure Resource Graph, prices it with the public Azure Retail Prices API and writes a client-style report: "Sie verlieren ca. X € pro Monat". Then `terraform destroy` removes everything.

## Stack
- IaC: Terraform (azurerm provider ~> 4.x), region `westeurope`
- Python 3.11+: `azure-identity`, `azure-mgmt-resourcegraph`, `requests`, `jinja2`, `pytest`
- CI: GitHub Actions (pytest, `terraform fmt -check`, `terraform validate`)

## Architecture
```
infra/            Terraform: RG + budget alert + 3 waste resources
scripts/          stop-vm.sh (az vm stop, WITHOUT deallocate)
src/waste_finder/
  queries/*.kql   one Resource Graph query per rule
  rules.py        runs queries -> list[Finding]
  pricing.py      Retail Prices API -> €/month per finding (cached)
  report.py       Markdown + HTML report (jinja2)
  cli.py          python -m waste_finder --subscription <id> [--demo]
tests/fixtures/   recorded Resource Graph + pricing responses
```
Flow: Resource Graph -> Findings -> Pricing -> Report.

## Decisions
- D1. Auth → default: `DefaultAzureCredential` (works after `az login`). No secrets in repo, ever.
- D2. Disk pricing → default: map disk size to the smallest tier that fits (e.g. 32 GB Standard HDD → S4 LRS), monthly price from Retail API. Switch to per-GB pricing if the tier meter is not found.
- D3. Pricing source in tests/CI → default: recorded JSON fixtures, no network. Live API only in real runs.
- D4. Report language → default: German headings and summary (client-facing), code and README in English.
- D5. "Stopped" VM → Terraform cannot leave a VM stopped, so `scripts/stop-vm.sh` runs `az vm stop` after apply. Rule matches `powerState == 'PowerState/stopped'` (not `deallocated`).
- D6. Smallest SKUs → default: VM `Standard_B1s`, disk 32 GB `Standard_LRS`, public IP `Standard` static. Switch VM size if B1s is unavailable in the region.

## Steps
- [x] 1. Skeleton [S]
  - README stub, .gitignore (tfstate, .terraform, .venv, .env), LICENSE MIT, pyproject.toml, `src/waste_finder/__init__.py`
  - `pytest` passes with one trivial test; CI workflow runs pytest
- [x] 2. Terraform base [M]
  - `infra/`: providers, variables (prefix, location, subscription_id, alert_email), resource group with tags, 5 € budget alert on the RG, outputs
  - `terraform fmt -check` and `terraform validate` pass (also in CI)
- [x] 3. Terraform waste resources [M] (see D5, D6)
  - Unattached managed disk, orphaned public IP, VM with vnet/subnet/NIC
  - `scripts/stop-vm.sh` stops the VM without deallocating; validate passes
- [x] 4. Resource Graph rules [M] (see D1, D5)
  - Three `.kql` files + `rules.py` returning `Finding(rule, resource_id, name, sku, size_gb, location)`
  - Unit tests with fixture responses cover all 3 rules
- [x] 5. Pricing [M] (see D2, D3)
  - `pricing.py` queries Retail Prices API with `currencyCode='EUR'`, returns €/month (hourly × 730 for VM/IP)
  - Tests with recorded fixtures; results cached to a local JSON file
- [x] 6. Report + CLI [M] (see D4)
  - `python -m waste_finder --subscription <id>` writes `report.md` and `report.html`, findings sorted by cost, total €/month and €/year
  - `--demo` flag runs fully on fixtures (no Azure needed); test covers it
- [x] 7. README [S]
  - Mermaid diagram, quick start (apply → stop-vm → run → destroy), sample report, "Why stopped ≠ deallocated", next steps (.NET port, more rules, Cost Management API, Azure DevOps pipeline)

## Out of scope
- More than 3 rules, Cost Management API, .NET port, Azure DevOps pipelines, dashboards, auto-remediation (all listed as "next steps" in README)
