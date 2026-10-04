# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A small FinOps "Kostencheck" for Azure (portfolio project, cloud/DevOps roles in Vienna / DACH). Terraform in `infra/` deploys a deliberately wasteful environment; a Python CLI finds the waste with Azure Resource Graph, prices it with the public Azure Retail Prices API and writes a German client report ("Sie verlieren ca. X € pro Monat"). `terraform destroy` removes everything.

The step-by-step extension plan and its design decisions (D1, D2, …) live in GitHub Issue #1; its comments are the progress log. Work happens in branches with one PR per change, merged only after CI is green; never push to `main` directly. Check `git log` and the code before assuming a planned feature exists.

## Commands

```bash
pip install -e ".[dev]"                 # install with test deps (use a venv)
pytest                                  # all tests, fully offline
pytest --cov                            # with coverage; fails below fail_under in pyproject.toml (95 %)
pytest tests/test_pricing.py::test_name # single test
ruff check . && ruff format --check .   # lint + format (line length 120)
mypy                                    # strict on src/
pre-commit install                      # optional: ruff + terraform fmt on commit
pip install pip-audit && pip freeze --exclude-editable > /tmp/req.txt && pip-audit -r /tmp/req.txt --no-deps --disable-pip   # what the CI audit job runs
python -m waste_finder --demo           # offline demo run -> reports/report.md + report.html
python -m waste_finder --subscription <id>   # real run, needs `az login` (Reader is enough)
python -m waste_finder --all-subscriptions --rules stopped_vm --exclude '*/resourceGroups/rg-x/*' --min-savings 5
python -m waste_finder --demo --format md,html,json,csv,sarif --fail-over 100 --summary summary.md   # exit code 3

cd infra
terraform fmt -check -recursive
terraform init -backend=false && terraform validate
terraform test                          # infra/tests/*.tftest.hcl, mocked providers, needs Terraform >= 1.11 (override_during)
tflint --init && tflint                 # config in infra/.tflint.hcl (azurerm ruleset)
checkov -d . --framework terraform      # optional locally (pip install checkov); CI runs it report-only
```

Windows: activate the venv with `.venv\Scripts\activate`; `scripts/stop-vm.ps1` instead of `stop-vm.sh`.

## Architecture

```
infra/                    Terraform: RG, 5 € budget alert, 3 waste resources (disk, VM, public IP)
  extra-waste.tf          opt-in waste for the newer rules, count = var.enable_extra_waste ? 1 : 0 (D3):
                          incremental snapshot of the orphaned disk, empty B1 Linux App Service plan,
                          internal Standard load balancer without rules (free); no NAT gateway (~0.04 €/h);
                          free clean-up resources: orphaned NIC, unattached NSG, empty resource group
  tests/*.tftest.hcl      terraform test, mock_provider "azurerm" + "tls"
  .tflint.hcl             tflint: recommended terraform preset + azurerm ruleset
scripts/stop-vm.(ps1|sh)  `az vm stop` WITHOUT deallocate (Terraform can't leave a VM "stopped")
src/waste_finder/
  registry.py             REGISTRY (rule id -> Rule: titles DE/EN, severity, KQL file, pricing strategy name,
                          why/action text, az command template, docs link); the single source of truth for rules
  models.py               Finding dataclass (severity, age_days, quantity, monthly_cost_eur, monthly_savings_eur;
                          is_free = priced at exactly 0), HOURS_PER_MONTH = 730
  queries/*.kql           one Resource Graph query per rule
  rules.py                load_query(rule) via the registry, find_waste(run_query, rules, min_age_days) -> list[Finding];
                          Scope (subscriptions | management group | all readable) + resource_graph_runner(scope)
  config.py               Settings from waste-finder.toml (tomllib) overridden by CLI flags; ignore tag
                          `waste-finder:ignore=true` + exclude globs on the resource ID; min_monthly_savings threshold;
                          formats, fail_over, snapshot_min_age_days, downgrade_lookback_days (-> Settings.min_age_days);
                          split_ignored / split_free / split_below_threshold
  pricing.py              STRATEGIES (strategy name -> pricing fn returning Price(cost, note, savings=None)),
                          Retail Prices API fetcher with 24 h JSON cache
  report.py, templates/   Jinja2 Markdown + HTML report, German; section "Aufräumen (kostenlos)" for free findings
  export.py               FORMATS; JSON (schema_version, docs/report.schema.json), CSV, SARIF 2.1.0 exporters;
                          render_summary (German Markdown for --summary / $GITHUB_STEP_SUMMARY)
  cli.py                  argparse entry point (`python -m waste_finder`, console script `waste-finder`);
                          exit codes 0 ok, 2 usage/config error, 3 monthly waste above --fail-over
  demo.py, demo/*.json    fake subscription + price list for --demo and tests
docs/report.schema.json   JSON Schema of report.json; tests validate the demo JSON against it (jsonschema, dev extra)
tests/                    pytest, no network (test_fetchers.py fakes requests and the Resource Graph SDK)
```

Flow: Resource Graph (scope) → `Finding`s of the selected rules (age-based rows below their minimum age dropped) → drop ignored/excluded → pricing → split off free clean-up findings (cost 0) → drop below threshold → report in the selected formats (md/html grouped by subscription plus the clean-up section, counts of ignored and below-threshold findings; json/csv/sarif from `export.py`, exporters take `(findings, summary, run, cleanup)`) → optional summary → exit code 3 if the total is above `fail_over`. The query runner (`Callable[[str], list[dict]]`) and the price fetcher (`Callable[[str], list[dict]]`, takes an OData filter) are injected, which is how tests and `--demo` run without Azure. `demo_runner` maps a KQL text back to its rule, so every rule needs an entry in `demo/resource_graph.json`; `demo_fetcher` evaluates only simple `field eq 'value' and ...` filters, so pricing filters must stay in that shape (or the demo fetcher must learn the new shape).

Cost vs. savings (D6): `Finding.monthly_cost_eur` is what the resource costs now, `monthly_savings_eur` is set only when acting saves less than the full cost (e.g. a downgrade). `Finding.savings_eur` falls back to the cost; the report total, the sort order and the CLI output use `savings_eur`. A pricing strategy sets savings through `Price.savings` (only `disk_downgrade` does: current tier minus the Standard HDD tier of the same size, never below 0); the md/html tables show "Kosten" and "Einsparung" columns, and `Summary.monthly_cost_eur` (md/html only, not in JSON) is mentioned when it differs from the total. If the reference price is missing the finding is unpriced rather than showing the full cost as savings.

### How to add a rule

1. `src/waste_finder/queries/<name>.kql`: project at least `id, name, resourceGroup, location, sku, tags` (plus `sizeGb` / `osType` / `quantity` if pricing needs them, `ageDays` for an age-based rule plus its entry in `Settings.min_age_days`).
2. `Rule(...)` entry in `REGISTRY` in `registry.py`: id, `title_de`, `title_en`, `severity` (`high|medium|low|info`; `info` + pricing `free` for a hygiene rule), `query_file`, `pricing`, `why_de`, `action_de`, `command` (`az ... --ids {id}`; `{name}` and `{subscription}` exist for commands without `--ids`, e.g. `az group delete`), `docs_url` (learn.microsoft.com), optional `quantity_unit_de` (report label for `quantity`, e.g. "Instanz(en)") and `age_label_de` (default "Tage alt").
3. Pricing: reuse a strategy name from `STRATEGIES` in `pricing.py` or add a new function there (filters in `field eq 'value' and ...` shape so `demo_fetcher` can evaluate them).
4. Demo data: rows under the rule id in `demo/resource_graph.json`, matching price items in `demo/prices.json`.
5. Tests: pricing cases in `tests/test_pricing.py`; `tests/test_registry.py` already fails if the KQL file, the strategy or the demo rows are missing.
6. README rules table and the rule ids in the `--rules` row of the flags table; regenerate `docs/sample-report.md` / `.html` from `python -m waste_finder --demo`.

The report templates, the exporters (JSON/CSV/SARIF rules) and the CLI read titles, severity, docs link and command from the registry; they need no change.

## Conventions and gotchas

- **Read-only tool.** Never add code that modifies or deletes Azure resources. Auth is `DefaultAzureCredential` only; no keys or secrets in code, tests or workflows.
- **No Azure in automated runs.** CI and scheduled builder runs have no Azure credentials. New features must be testable offline with fixtures; live-Azure workflows must skip cleanly when repo variables are not set.
- **Cost discipline.** New Terraform waste resources are opt-in, smallest SKU, README states their approximate €/hour. Nothing that creates Azure resources runs on a schedule.
- **Prices** are list prices (Retail API, `currencyCode='EUR'` unless `currency` is configured; the `*_eur` field names stay and then hold the configured currency; one price cache file per currency), monthly = hourly × 730. Disks are priced by the smallest tier that fits (32 GB Standard HDD → `S4 LRS`, Standard HDD starts at S4), using exactly the `<tier> Disk` meter of a `... Managed Disks` product: SSD tiers also have a `<tier> Disk Mount` meter (per mount of a shared disk) that must not be picked.
- **Settings precedence**: defaults < `waste-finder.toml` < CLI flags; a flag replaces a list from the file. New settings go into `config.Settings`, `load_config` (unknown keys are rejected) and a CLI flag; tests in `tests/test_config.py`.
- **JSON output** is a contract (later runs read it for trends): changing a field means bumping `export.SCHEMA_VERSION` (minor = new optional field, major = rename/removal) and updating `docs/report.schema.json`; the schema has `additionalProperties: false`, so the tests catch drift.
- **Subscription grouping** uses `Finding.subscription_id`, parsed from the resource ID; demo data has two subscriptions and one resource tagged `waste-finder:ignore=true`.
- **Age-based rules** (`old_snapshot`, `premium_disk_deallocated_vm`): the KQL projects `ageDays`, computed by Resource Graph with `now()`, so demo rows carry a fixed `ageDays` and stay stable over time. `find_waste` drops rows younger than `Settings.min_age_days[rule]` before they become findings (they are not counted as ignored). `Finding.age_days` shows up in the report (label `Rule.age_label_de`) and in JSON/CSV (`age_days`, schema 1.1). Deallocation time comes from the disk's `properties.LastOwnershipUpdateTime` (capital L; last attach/detach or VM deallocate/start) with `diskState == 'Reserved'` (attached to a deallocated VM).
- **Snapshots** are priced per GB-month of the snapshot meter (`Snapshots LRS|ZRS` of the Standard HDD or Premium SSD product) × provisioned size: an upper bound, Azure bills the used size and Resource Graph does not expose it.
- **App Service plans** are priced from one Retail API call per region (`serviceName eq 'Azure App Service'`), matched in Python: hourly unit, product ends with ` - Linux` for Linux plans, `skuName` without spaces = ARM `sku.name` (`P1 v3` vs `P1v3`); × 730 × instances (`quantity`, from `sku.capacity`). Elastic Premium / Workflow Standard plans have no such meter and stay unpriced.
- **Idle network** (verified against the Retail API): NAT gateways bill the hourly `<sku> Gateway` meter even without subnets or traffic (no hourly meter for StandardV2: unpriced). Standard load balancers bill only for rules (`Standard Included LB Rules and Outbound Rules` for the first 5, `... Overage ...` per further rule; the `... - Free` meters are not used); no rules = no hourly charge. Both price lists are global (`armRegionName` 'Global'), so pricing prefers the exact region, then 'Global'. The LB query counts backend members with `mv-expand` (Resource Graph has no `mv-apply`) and projects the rule count as `quantity`.
- **Free findings**: `price_findings` sets `severity = "info"` for every finding priced at exactly 0 (e.g. a load balancer without rules); unpriced (`None`) findings keep their severity.
- **Free clean-up findings** (`orphaned_nic`, `unattached_nsg`, `empty_resource_group`, pricing `free`, and any other finding priced at 0 such as a load balancer without rules): `config.split_free` takes them out after pricing, so they are not in the total, not in `summary.count` and not subject to `min_monthly_savings`. They are shown in "Aufräumen (kostenlos)" (md/html, with their own commands), counted in `Summary.cleanup`, exported as JSON `cleanup` (schema 1.3), appended to CSV and SARIF (level `note`). The "Warum kostet das Geld?" list skips pricing-`free` rules; the clean-up section explains the rules it lists.
- **Empty resource groups** come from `ResourceContainers` with a `join kind=leftouter` on a per-group resource count (Resource Graph supports no anti-join); groups with `managedBy` set are skipped.
- **Checkov and opt-in resources**: resources behind `count = var.enable_extra_waste ? 1 : 0` are not evaluated with the default variables, so CI does not scan them. Check them locally with a tfvars file that sets `enable_extra_waste = true` (`checkov -d infra --var-file <file>`) before adding inline skips.
- **"Stopped" ≠ "deallocated"**: the VM rule matches `PowerState/stopped` only; deallocated VMs don't bill compute.
- **Lint/types**: code passes `ruff` and `mypy --strict` (config in `pyproject.toml`) without blanket ignores; Resource Graph rows are `rules.Row`, price items `pricing.PriceItem`, pricing functions `pricing.PricingStrategy` returning `pricing.Price` (rows and items are `dict[str, Any]`).
- **Language**: report text German; code, CLI help, README, docs, commits in English.
- `*.tfvars` (except `example.tfvars`) and `*.tfstate` are git-ignored: state holds the generated SSH key.

## CI

`.github/workflows/ci.yml` runs on PRs and pushes to `main`: job `lint` (`ruff check`, `ruff format --check`, `mypy`), job `audit` (`pip-audit` on `pip freeze --exclude-editable` of the installed `.[dev]` env, so the runner's own pip/setuptools are not audited; fails on any known vulnerability, fix by raising the lower bound in `pyproject.toml`), job `python` (pytest with coverage on 3.11 / 3.12 / 3.13, floor = `fail_under` in `pyproject.toml`; JUnit results published by `dorny/test-reporter`, skipped for Dependabot/fork PRs whose token cannot create check runs; artifacts `coverage-<version>` and, from 3.12, `demo-report` with all five formats and the summary on the run page) job `terraform` (`fmt -check`, `init -backend=false`, `validate`, `terraform test`, `tflint`) and job `config-scan` (Checkov on `infra/`, `--soft-fail`, SARIF uploaded to the Security tab, upload skipped for Dependabot/fork PRs). Intentional Checkov findings are skipped inline (`#checkov:skip=ID:reason`) in the resource block; fix real findings instead of skipping them. New Terraform resources get assertions in `infra/tests/`; when an assertion needs a value that is only known after apply (an ID), use `override_resource` with `override_during = plan` instead of `command = apply` (mocked IDs fail azurerm's ID validation). Coverage floor per D7: measured value rounded down to 5, never below 80; raise it when coverage grows, never lower it to get green. `.github/workflows/codeql.yml` runs CodeQL (Python, default query suite, `build-mode: none`) on PRs, `main` and weekly; results go to the Security tab. Vulnerability reporting and scope: `SECURITY.md`.

Dependabot (`.github/dependabot.yml`) opens weekly PRs for pip, GitHub Actions and Terraform providers: minor + patch bumps grouped into one PR per ecosystem, each major bump as its own PR. Merge policy: squash-merge a Dependabot PR once CI is green; a major bump that fails CI is fixed on its branch if the fix is small and in scope, otherwise closed with a one-line reason; if a merged bump makes a statement in CLAUDE.md, README.md or the Stack line of issue #1 stale, fix it.
