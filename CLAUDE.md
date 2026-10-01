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

cd infra
terraform fmt -check -recursive
terraform init -backend=false && terraform validate
terraform test                          # infra/tests/*.tftest.hcl, mocked providers, needs Terraform >= 1.7
tflint --init && tflint                 # config in infra/.tflint.hcl (azurerm ruleset)
checkov -d . --framework terraform      # optional locally (pip install checkov); CI runs it report-only
```

Windows: activate the venv with `.venv\Scripts\activate`; `scripts/stop-vm.ps1` instead of `stop-vm.sh`.

## Architecture

```
infra/                    Terraform: RG, 5 € budget alert, 3 waste resources (disk, VM, public IP)
  tests/*.tftest.hcl      terraform test, mock_provider "azurerm" + "tls"
  .tflint.hcl             tflint: recommended terraform preset + azurerm ruleset
scripts/stop-vm.(ps1|sh)  `az vm stop` WITHOUT deallocate (Terraform can't leave a VM "stopped")
src/waste_finder/
  registry.py             REGISTRY (rule id -> Rule: titles DE/EN, severity, KQL file, pricing strategy name,
                          why/action text, az command template, docs link); the single source of truth for rules
  models.py               Finding dataclass (severity, monthly_cost_eur, monthly_savings_eur), HOURS_PER_MONTH = 730
  queries/*.kql           one Resource Graph query per rule
  rules.py                load_query(rule) via the registry, find_waste(run_query) -> list[Finding]
  pricing.py              STRATEGIES (strategy name -> pricing fn), Retail Prices API fetcher with 24 h JSON cache
  report.py, templates/   Jinja2 Markdown + HTML report, German
  cli.py                  argparse entry point (`python -m waste_finder`, console script `waste-finder`)
  demo.py, demo/*.json    fake subscription + price list for --demo and tests
tests/                    pytest, no network (test_fetchers.py fakes requests and the Resource Graph SDK)
```

Flow: Resource Graph → `Finding`s → pricing → report. The query runner (`Callable[[str], list[dict]]`) and the price fetcher (`Callable[[str], list[dict]]`, takes an OData filter) are injected, which is how tests and `--demo` run without Azure. `demo_runner` maps a KQL text back to its rule, so every rule needs an entry in `demo/resource_graph.json`; `demo_fetcher` evaluates only simple `field eq 'value' and ...` filters, so pricing filters must stay in that shape (or the demo fetcher must learn the new shape).

Cost vs. savings (D6): `Finding.monthly_cost_eur` is what the resource costs now, `monthly_savings_eur` is set only when acting saves less than the full cost (e.g. a downgrade). `Finding.savings_eur` falls back to the cost; the report total, the sort order and the CLI output use `savings_eur`.

### How to add a rule

1. `src/waste_finder/queries/<name>.kql`: project at least `id, name, resourceGroup, location, sku, tags` (plus `sizeGb` / `osType` if pricing needs them).
2. `Rule(...)` entry in `REGISTRY` in `registry.py`: id, `title_de`, `title_en`, `severity` (`high|medium|low|info`), `query_file`, `pricing`, `why_de`, `action_de`, `command` (`az ... --ids {id}`), `docs_url` (learn.microsoft.com).
3. Pricing: reuse a strategy name from `STRATEGIES` in `pricing.py` or add a new function there (filters in `field eq 'value' and ...` shape so `demo_fetcher` can evaluate them).
4. Demo data: rows under the rule id in `demo/resource_graph.json`, matching price items in `demo/prices.json`.
5. Tests: pricing cases in `tests/test_pricing.py`; `tests/test_registry.py` already fails if the KQL file, the strategy or the demo rows are missing.
6. README rules table; regenerate `docs/sample-report.md` / `.html` from `python -m waste_finder --demo`.

The report templates and the CLI read titles, severity, docs link and command from the registry; they need no change.

## Conventions and gotchas

- **Read-only tool.** Never add code that modifies or deletes Azure resources. Auth is `DefaultAzureCredential` only; no keys or secrets in code, tests or workflows.
- **No Azure in automated runs.** CI and scheduled builder runs have no Azure credentials. New features must be testable offline with fixtures; live-Azure workflows must skip cleanly when repo variables are not set.
- **Cost discipline.** New Terraform waste resources are opt-in, smallest SKU, README states their approximate €/hour. Nothing that creates Azure resources runs on a schedule.
- **Prices** are list prices (Retail API, `currencyCode='EUR'`), monthly = hourly × 730. Disks are priced by the smallest tier that fits (32 GB Standard HDD → `S4 LRS`, Standard HDD starts at S4).
- **"Stopped" ≠ "deallocated"**: the VM rule matches `PowerState/stopped` only; deallocated VMs don't bill compute.
- **Lint/types**: code passes `ruff` and `mypy --strict` (config in `pyproject.toml`) without blanket ignores; Resource Graph rows are `rules.Row`, price items `pricing.PriceItem`, pricing functions `pricing.PricingStrategy` (both `dict[str, Any]`).
- **Language**: report text German; code, CLI help, README, docs, commits in English.
- `*.tfvars` (except `example.tfvars`) and `*.tfstate` are git-ignored: state holds the generated SSH key.

## CI

`.github/workflows/ci.yml` runs on PRs and pushes to `main`: job `lint` (`ruff check`, `ruff format --check`, `mypy`), job `audit` (`pip-audit` on `pip freeze --exclude-editable` of the installed `.[dev]` env, so the runner's own pip/setuptools are not audited; fails on any known vulnerability, fix by raising the lower bound in `pyproject.toml`), job `python` (pytest with coverage on 3.11 / 3.12 / 3.13, floor = `fail_under` in `pyproject.toml`; JUnit results published by `dorny/test-reporter`, skipped for Dependabot/fork PRs whose token cannot create check runs; artifacts `coverage-<version>` and, from 3.12, `demo-report`) job `terraform` (`fmt -check`, `init -backend=false`, `validate`, `terraform test`, `tflint`) and job `config-scan` (Checkov on `infra/`, `--soft-fail`, SARIF uploaded to the Security tab, upload skipped for Dependabot/fork PRs). Intentional Checkov findings are skipped inline (`#checkov:skip=ID:reason`) in the resource block; fix real findings instead of skipping them. New Terraform resources get assertions in `infra/tests/`. Coverage floor per D7: measured value rounded down to 5, never below 80; raise it when coverage grows, never lower it to get green. `.github/workflows/codeql.yml` runs CodeQL (Python, default query suite, `build-mode: none`) on PRs, `main` and weekly; results go to the Security tab. Vulnerability reporting and scope: `SECURITY.md`.

Dependabot (`.github/dependabot.yml`) opens weekly PRs for pip, GitHub Actions and Terraform providers: minor + patch bumps grouped into one PR per ecosystem, each major bump as its own PR. Merge policy: squash-merge a Dependabot PR once CI is green; a major bump that fails CI is fixed on its branch if the fix is small and in scope, otherwise closed with a one-line reason; if a merged bump makes a statement in CLAUDE.md, README.md or the Stack line of issue #1 stale, fix it.
