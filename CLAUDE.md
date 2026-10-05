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
mypy                                    # strict on src/ and scripts/
pre-commit install                      # optional: ruff + terraform fmt on commit
pip install pip-audit && pip freeze --exclude-editable > /tmp/req.txt && pip-audit -r /tmp/req.txt --no-deps --disable-pip   # what the CI audit job runs
python -m waste_finder --demo           # offline demo run -> reports/report.md + report.html
cp reports/report.md docs/sample-report.md && cp reports/report.html docs/sample-report.html   # after demo output changes
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --user-data-dir=/tmp/chrome-shot --hide-scrollbars \
  --blink-settings=preferredColorScheme=1 --force-device-scale-factor=2 --window-size=1100,900 \
  --screenshot=docs/sample-report.png "file://$PWD/docs/sample-report.html"   # README screenshot (macOS; may not exit, Ctrl-C after the file exists)
waste-finder --version                  # version from the git tag (setuptools-scm); reinstall after tagging
pip install build twine && python -m build && twine check dist/*   # sdist + wheel like release.yml
docker build --build-arg VERSION=0.0.0+local -t azure-waste-finder .  # needs Docker; CI job `docker` does this
docker run --rm azure-waste-finder --demo                             # entrypoint is waste-finder, user uid 10001
python -m waste_finder --subscription <id>   # real run, needs `az login` (Reader is enough)
python -m waste_finder --demo --cost-source actual   # actual costs from the demo Cost Management answers
python -m waste_finder --demo --previous ''          # demo without the built-in trend (default: demo/previous-report.json)
python -m waste_finder --subscription <id> --format json --previous reports/old/report.json   # trend since an earlier run
python -m waste_finder --all-subscriptions --rules stopped_vm --exclude '*/resourceGroups/rg-x/*' --min-savings 5
python -m waste_finder --demo --format md,html,json,csv,sarif --fail-over 100 --summary summary.md   # exit code 3
python scripts/finops_issue.py --report reports/report.json --threshold 10 --dry-run   # issue body finops-check.yml would write
python scripts/e2e_assert.py --report reports/report.json --expected expected.json --resource-group <rg>   # e2e.yml check
python scripts/build_workbook.py        # regenerate workbooks/waste-finder.workbook.json after changing a rule or KQL file
python scripts/build_workbook.py --check   # exit 1 when the committed workbook is out of date (tests/test_workbook.py too)

cd infra
terraform fmt -check -recursive
terraform init -backend=false && terraform validate
terraform test                          # infra/tests/*.tftest.hcl, mocked providers, needs Terraform >= 1.11 (override_during)
tflint --init && tflint                 # config in infra/.tflint.hcl (azurerm ruleset)
checkov -d . --framework terraform      # optional locally (pip install checkov); CI runs it report-only

cd infra/github-oidc                    # second Terraform root, same checks (CI matrix over both roots)
terraform init -backend=false && terraform validate && terraform test && tflint --init && tflint
```

Windows: activate the venv with `.venv\Scripts\activate`; `scripts/stop-vm.ps1` instead of `stop-vm.sh`.

## Architecture

```
Dockerfile                multi-stage python:3.12-slim (digest-pinned): build stage builds the wheel with
                          SETUPTOOLS_SCM_PRETEND_VERSION=$VERSION (.git is not in the context) into /opt/venv,
                          runtime stage copies the venv, user finder (10001), WORKDIR /work (mode 1777, so
                          `--user $(id -u)` can write too; reports/ and .cache/ land there), ENTRYPOINT ["waste-finder"]
.dockerignore             allowlist: pyproject.toml, README.md, LICENSE, src/
azure-pipelines.yml       Azure DevOps twin of finops-check.yml (never runs in GitHub): weekly cron on main
                          (always: true), parameters costSource (retail|actual) and failOver (default " ", blank =
                          off), DownloadPipelineArtifact@2 of the previous `finops-report` (continueOnError) ->
                          AzureCLI@2 (azureSubscription = ${{ variables.azureServiceConnection }}, compile time) ->
                          ##vso[task.uploadsummary] -> PublishPipelineArtifact@1; setup in docs/azure-devops.md
infra/                    Terraform: RG, 5 € budget alert, 3 waste resources (disk, VM, public IP);
                          var.resource_group_name (default null) deploys into an existing group via
                          data.azurerm_resource_group.existing instead of azurerm_resource_group.demo[0]
                          (count, `moved` block from the old address); resources use local.resource_group_name /
                          local.location / local.resource_group_id
  extra-waste.tf          opt-in waste for the newer rules, count = var.enable_extra_waste ? 1 : 0 (D3):
                          incremental snapshot of the orphaned disk, empty B1 Linux App Service plan,
                          internal Standard load balancer without rules (free); no NAT gateway (~0.04 €/h);
                          free clean-up resources: orphaned NIC, unattached NSG, empty resource group
  workbook.tf             opt-in azurerm_application_insights_workbook, count = var.enable_workbook ? 1 : 0:
                          data_json = file("${path.module}/../workbooks/waste-finder.workbook.json"), name =
                          uuidv5 of the prefix (must be a GUID, stable across applies), source_id "azure monitor";
                          output workbook_id
  tests/*.tftest.hcl      terraform test, mock_provider "azurerm" + "tls"
  .tflint.hcl             tflint: recommended terraform preset + azurerm ruleset
  github-oidc/            own root (azuread ~> 3.10 + azurerm), applied once by the owner (D10), never in CI:
                          app registration + SP (no secret), federated credentials for_each over
                          {branch = repo:<repo>:ref:refs/heads/main, environment = repo:<repo>:environment:azure-e2e},
                          Reader + Cost Management Reader on the subscription; enable_e2e (default false) adds RG
                          awf-e2e-rg (tag waste-finder:ignore=true) + Contributor on it only; outputs client/tenant/
                          subscription ID, github_variables, gh_variable_commands; tests/ mock both providers with
                          override_during = plan and well-formed default IDs
scripts/stop-vm.(ps1|sh)  `az vm stop` WITHOUT deallocate (Terraform can't leave a VM "stopped")
scripts/finops_issue.py   CI helper for finops-check.yml (not part of the package): load_summary(report.json) ->
                          decide(monthly, count, threshold, open issue) -> create | update | close | none;
                          GhIssues talks to the gh CLI through an injectable runner; --dry-run prints the body
scripts/build_workbook.py generates workbooks/waste-finder.workbook.json (Notebook/1.0) from REGISTRY + queries/:
                          intro text, parameters (subscription picker, AGE_PARAMETERS for the age-based rules with
                          Settings defaults), per rule a text (title, priority, why/action, docs) + a Resource Graph
                          query (queryType 1) = KQL file unchanged + tail (ignore tag, age filter, `command` column
                          built from Rule.command by kql_command); paid rules first, free ones under "Aufräumen
                          (kostenlos)"; deterministic (uuid5 IDs); --check exits 1 when the file is stale
scripts/e2e_assert.py     CI helper for e2e.yml: check_report(report, expected_findings, resource_group) -> one Check
                          per BASE_RULES entry (rule id -> expected_findings key, `orphaned_ip` for the public IP):
                          same rule + name + group (case-insensitive), monthly_cost > 0; exit 0 / 1 (retry) / 2
src/waste_finder/
  registry.py             REGISTRY (rule id -> Rule: titles DE/EN, severity, KQL file, pricing strategy name,
                          why/action text, az command template, docs link); the single source of truth for rules
  models.py               Finding dataclass (severity, age_days, quantity, monthly_cost_eur, monthly_savings_eur,
                          cost_source retail|actual; is_free = priced at exactly 0), HOURS_PER_MONTH = 730
  queries/*.kql           one Resource Graph query per rule
  rules.py                load_query(rule) via the registry, find_waste(run_query, rules, min_age_days) -> list[Finding];
                          Scope (subscriptions | management group | all readable) + resource_graph_runner(scope)
  config.py               Settings from waste-finder.toml (tomllib) overridden by CLI flags; ignore tag
                          `waste-finder:ignore=true` + exclude globs on the resource ID; min_monthly_savings threshold;
                          formats, fail_over, cost_source, snapshot_min_age_days, downgrade_lookback_days
                          (-> Settings.min_age_days);
                          split_ignored / split_free / split_below_threshold
  pricing.py              STRATEGIES (strategy name -> pricing fn returning Price(cost, note, savings=None)),
                          Retail Prices API fetcher with 24 h JSON cache; PARTIAL_SAVINGS_STRATEGIES
  costs.py                --cost-source actual: Cost Management Query API (AmortizedCost, last 30 full days,
                          grouped by ResourceId, one POST per subscription with findings, nextLink paging,
                          429 retry); collect_actual_costs (failed subscription -> warning, retail stays),
                          apply_actual_costs (per-finding fallback to retail)
  report.py, templates/   Jinja2 Markdown + HTML report, German; section "Aufräumen (kostenlos)" for free findings;
                          HTML only: rule_chart (savings per rule -> ChartBar, largest = CHART_MAX_PERCENT 75 %, skipped
                          below two rules) drawn as inline SVG, severity_counts + SEVERITY_RANK (badges, data-sort),
                          tables class="sortable" + one inline vanilla-JS sorter, print CSS, dark mode
  export.py               FORMATS; JSON (schema_version, docs/report.schema.json), CSV, SARIF 2.1.0 exporters;
                          render_summary (German Markdown for --summary / $GITHUB_STEP_SUMMARY)
  cli.py                  argparse entry point (`python -m waste_finder`, console script `waste-finder`);
                          exit codes 0 ok, 2 usage/config error, 3 monthly waste above --fail-over
  trend.py                --previous: load_previous (any 1.x report.json -> PreviousReport), compare -> Trend
                          (new / resolved / unchanged by (rule, lower-case resource ID), only the rules of this run;
                          rows() for the report table)
  demo.py, demo/*.json    fake subscriptions, price list, Cost Management answers (cost_management.json, keyed by
                          subscription) and an earlier run (previous-report.json, used by --demo unless --previous)
workbooks/                waste-finder.workbook.json, generated (never edit by hand); tests/test_workbook.py asserts
                          it equals build_workbook.render()
docs/report.schema.json   JSON Schema of report.json; tests validate the demo JSON against it (jsonschema, dev extra)
docs/azure-devops.md      owner setup of the Azure DevOps pipeline (service connection with workload identity
                          federation, reusing the infra/github-oidc app via a second federated credential)
tests/                    pytest, no network (test_fetchers.py fakes requests and the Resource Graph SDK)
  test_finops_issue.py    the issue logic with a fake gh; test_workflows.py parses .github/workflows/*.yml (PyYAML)
                          and asserts D2/D3: jobs with azure/login have `if: vars.AZURE_CLIENT_ID != ''` and
                          id-token: write, workflows running `terraform apply` are workflow_dispatch only
  fixtures/cost_management/  Cost Management Query API responses in the documented format (paging, PreTaxCost/USD,
                          403, 429) for test_costs.py
```

Flow: Resource Graph (scope) → `Finding`s of the selected rules (age-based rows below their minimum age dropped) → drop ignored/excluded → pricing (retail) → with `--cost-source actual`: Cost Management per subscription with findings replaces the retail amounts where it has a row → split off free clean-up findings (cost 0) → drop below threshold → optional trend against `--previous` → report in the selected formats (md/html grouped by subscription plus the clean-up section, counts of ignored and below-threshold findings; json/csv/sarif from `export.py`, exporters take `(findings, summary, run, cleanup, trend)`) → optional summary → exit code 3 if the total is above `fail_over`. The query runner (`Callable[[str], list[dict]]`) and the price fetcher (`Callable[[str], list[dict]]`, takes an OData filter) are injected, which is how tests and `--demo` run without Azure. `demo_runner` maps a KQL text back to its rule, so every rule needs an entry in `demo/resource_graph.json`; `demo_fetcher` evaluates only simple `field eq 'value' and ...` filters, so pricing filters must stay in that shape (or the demo fetcher must learn the new shape).

Cost vs. savings (D6): `Finding.monthly_cost_eur` is what the resource costs now, `monthly_savings_eur` is set only when acting saves less than the full cost (e.g. a downgrade). `Finding.savings_eur` falls back to the cost; the report total, the sort order and the CLI output use `savings_eur`. A pricing strategy sets savings through `Price.savings` (only `disk_downgrade` does: current tier minus the Standard HDD tier of the same size, never below 0); the md/html tables show "Kosten" and "Einsparung" columns, and `Summary.monthly_cost_eur` (md/html only, not in JSON) is mentioned when it differs from the total. If the reference price is missing the finding is unpriced rather than showing the full cost as savings.

### How to add a rule

1. `src/waste_finder/queries/<name>.kql`: project at least `id, name, resourceGroup, location, sku, tags` (plus `sizeGb` / `osType` / `quantity` if pricing needs them, `ageDays` for an age-based rule plus its entry in `Settings.min_age_days`).
2. `Rule(...)` entry in `REGISTRY` in `registry.py`: id, `title_de`, `title_en`, `severity` (`high|medium|low|info`; `info` + pricing `free` for a hygiene rule), `query_file`, `pricing`, `why_de`, `action_de`, `command` (`az ... --ids {id}`; `{name}` and `{subscription}` exist for commands without `--ids`, e.g. `az group delete`), `docs_url` (learn.microsoft.com), optional `quantity_unit_de` (report label for `quantity`, e.g. "Instanz(en)") and `age_label_de` (default "Tage alt").
3. Pricing: reuse a strategy name from `STRATEGIES` in `pricing.py` or add a new function there (filters in `field eq 'value' and ...` shape so `demo_fetcher` can evaluate them).
4. Demo data: rows under the rule id in `demo/resource_graph.json`, matching price items in `demo/prices.json`.
5. Tests: pricing cases in `tests/test_pricing.py`; `tests/test_registry.py` already fails if the KQL file, the strategy or the demo rows are missing.
6. README rules table and the rule ids in the `--rules` row of the flags table; regenerate `docs/sample-report.md` / `.html` from `python -m waste_finder --demo`.
7. Regenerate the Azure Workbook: `python scripts/build_workbook.py` (`tests/test_workbook.py` fails until you do). An age-based rule also needs an entry in `AGE_PARAMETERS` there; a new placeholder in `command` needs one in `COMMAND_FIELDS`.

The report templates, the exporters (JSON/CSV/SARIF rules) and the CLI read titles, severity, docs link and command from the registry; they need no change.

## Conventions and gotchas

- **Read-only tool.** Never add code that modifies or deletes Azure resources. Auth is `DefaultAzureCredential` only; no keys or secrets in code, tests or workflows.
- **No Azure in automated runs.** CI and scheduled builder runs have no Azure credentials. New features must be testable offline with fixtures; live-Azure workflows must skip cleanly when repo variables are not set.
- **Cost discipline.** New Terraform waste resources are opt-in, smallest SKU, README states their approximate €/hour. Nothing that creates Azure resources runs on a schedule.
- **Prices** are list prices (Retail API, `currencyCode='EUR'` unless `currency` is configured; the `*_eur` field names stay and then hold the configured currency; one price cache file per currency), monthly = hourly × 730. Disks are priced by the smallest tier that fits (32 GB Standard HDD → `S4 LRS`, Standard HDD starts at S4), using exactly the `<tier> Disk` meter of a `... Managed Disks` product: SSD tiers also have a `<tier> Disk Mount` meter (per mount of a shared disk) that must not be picked.
- **Settings precedence**: defaults < `waste-finder.toml` < CLI flags; a flag replaces a list from the file. New settings go into `config.Settings`, `load_config` (unknown keys are rejected) and a CLI flag; tests in `tests/test_config.py`.
- **JSON output** is a contract (`--previous` reads it for trends; currently schema 1.5: 1.4 added `cost_source`, `cost_period` and `summary.actual_costs`, 1.5 `trend`, finding `trend` and `previous_monthly_savings`): changing a field means bumping `export.SCHEMA_VERSION` (minor = new optional field, major = rename/removal) and updating `docs/report.schema.json`; the schema has `additionalProperties: false`, so the tests catch drift.
- **Subscription grouping** uses `Finding.subscription_id`, parsed from the resource ID; demo data has two subscriptions and one resource tagged `waste-finder:ignore=true`.
- **Age-based rules** (`old_snapshot`, `premium_disk_deallocated_vm`): the KQL projects `ageDays`, computed by Resource Graph with `now()`, so demo rows carry a fixed `ageDays` and stay stable over time. `find_waste` drops rows younger than `Settings.min_age_days[rule]` before they become findings (they are not counted as ignored). `Finding.age_days` shows up in the report (label `Rule.age_label_de`) and in JSON/CSV (`age_days`, schema 1.1). Deallocation time comes from the disk's `properties.LastOwnershipUpdateTime` (capital L; last attach/detach or VM deallocate/start) with `diskState == 'Reserved'` (attached to a deallocated VM).
- **Snapshots** are priced per GB-month of the snapshot meter (`Snapshots LRS|ZRS` of the Standard HDD or Premium SSD product) × provisioned size: an upper bound, Azure bills the used size and Resource Graph does not expose it.
- **App Service plans** are priced from one Retail API call per region (`serviceName eq 'Azure App Service'`), matched in Python: hourly unit, product ends with ` - Linux` for Linux plans, `skuName` without spaces = ARM `sku.name` (`P1 v3` vs `P1v3`); × 730 × instances (`quantity`, from `sku.capacity`). Elastic Premium / Workflow Standard plans have no such meter and stay unpriced.
- **Idle network** (verified against the Retail API): NAT gateways bill the hourly `<sku> Gateway` meter even without subnets or traffic (no hourly meter for StandardV2: unpriced). Standard load balancers bill only for rules (`Standard Included LB Rules and Outbound Rules` for the first 5, `... Overage ...` per further rule; the `... - Free` meters are not used); no rules = no hourly charge. Both price lists are global (`armRegionName` 'Global'), so pricing prefers the exact region, then 'Global'. The LB query counts backend members with `mv-expand` (Resource Graph has no `mv-apply`) and projects the rule count as `quantity`.
- **Actual costs** (`--cost-source actual`, `costs.py`): the 30-day amortized sum is the monthly amount (not scaled to 730 h). Cost Management returns lower-case resource IDs, so matching is on `resource_id.lower()`. A finding keeps its retail price when there is no row, the row's currency differs from the report currency (counted, CLI note) or its subscription's query failed (CLI warning); `Finding.cost_source` is `"retail"` / `"actual"` / `None` (unpriced) and drives the report column "Quelle" (shown only for actual runs; the retail report is unchanged). Strategies in `pricing.PARTIAL_SAVINGS_STRATEGIES` (downgrades) keep the retail savings/cost ratio and stay unpriced without a retail result. After applying, severity is recomputed (`info` when savings are 0, else the rule severity). The query needs Cost Management Reader (or Reader). Fixtures follow the documented response format; they were not recorded against a live subscription.
- **Trend** (`--previous`, `trend.py`): same finding = same rule + resource ID (lower-case). Only `settings.rules` are compared; clean-up findings are not compared; unpriced amounts count as 0. A previous report in another currency is a usage error (exit 2); another cost source only adds a note. `demo/previous-report.json` is a schema-1.3 report on purpose (proves older reports load and validate); it is the demo run of 2026-09-04 with `natgw-old-hub` and `sap-test-db-data` missing, `build-agent-01` and `pip-old-vpn` present and `asp-intranet-legacy` at 1 instance, so the demo trend is -9,97 €. When demo findings or prices change, the demo trend numbers in tests and the sample report change too.
- **Free findings**: `price_findings` sets `severity = "info"` for every finding priced at exactly 0 (e.g. a load balancer without rules); unpriced (`None`) findings keep their severity.
- **Free clean-up findings** (`orphaned_nic`, `unattached_nsg`, `empty_resource_group`, pricing `free`, and any other finding priced at 0 such as a load balancer without rules): `config.split_free` takes them out after pricing, so they are not in the total, not in `summary.count` and not subject to `min_monthly_savings`. They are shown in "Aufräumen (kostenlos)" (md/html, with their own commands), counted in `Summary.cleanup`, exported as JSON `cleanup` (schema 1.3), appended to CSV and SARIF (level `note`). The "Warum kostet das Geld?" list skips pricing-`free` rules; the clean-up section explains the rules it lists.
- **Empty resource groups** come from `ResourceContainers` with a `join kind=leftouter` on a per-group resource count (Resource Graph supports no anti-join); groups with `managedBy` set are skipped.
- **Checkov and opt-in resources**: resources behind `count = var.enable_extra_waste ? 1 : 0` are not evaluated with the default variables, so CI does not scan them. Check them locally with a tfvars file that sets `enable_extra_waste = true` (`checkov -d infra --var-file <file>`) before adding inline skips.
- **"Stopped" ≠ "deallocated"**: the VM rule matches `PowerState/stopped` only; deallocated VMs don't bill compute.
- **Lint/types**: code passes `ruff` and `mypy --strict` (config in `pyproject.toml`) without blanket ignores; Resource Graph rows are `rules.Row`, price items `pricing.PriceItem`, pricing functions `pricing.PricingStrategy` returning `pricing.Price` (rows and items are `dict[str, Any]`).
- **HTML report** (`templates/report.html.j2`, `tests/test_report_html.py`): one self-contained file (Pages, e-mail): no `<link>`, no `src=`, no `url(`/`@import`, no CDN or framework; the only script is the inline sorter, and the report must read well without it (rows come sorted by savings, the server-side `aria-sort="descending"` on "Einsparung" says so). Sort keys: `data-sort` on a cell wins (severity rank), else `th.num` columns parse the German amount (`1.234,50 €`; `n/a`/`–` sort lowest), else text with `localeCompare(…, "de")`; `th.nosort` (Empfehlung) gets no button. Every color is a CSS variable with a light, a dark (`prefers-color-scheme`) and a print value; the print block comes last so paper is light even in dark mode. The chart is an SVG without viewBox (user units = CSS px, so text does not shrink on phones), bars as `%` widths with the value label at `x="<pct>%" dx="8"`; a 4 px square rect makes the baseline end square. Existing tests match exact HTML snippets (`<th>Quelle</th>`, `<td class="num">48,43 €</td>`, `<h2 id="aufraeumen">`), so keep those cells attribute-free. The Markdown report has none of this. Headless Chrome is the only way here to look at it (screenshots, `--dump-dom`, `--print-to-pdf`); its window is at least 500 px wide.
- **Language**: report text German; code, CLI help, README, docs, commits in English.
- `*.tfvars` (except `example.tfvars`) and `*.tfstate` are git-ignored: state holds the generated SSH key.
- **scripts/*.py** are imported by tests as top-level modules (`pythonpath = ["scripts"]` for pytest, `src = ["src", "scripts"]` for ruff's isort, `files = ["src", "scripts"]` for mypy); they are not in the wheel and not in the coverage measurement (`source = ["waste_finder"]`), so keep their tests thorough. `release.yml` runs the full suite with `src/` removed, which still works because `scripts/` stays.
- **FinOps issue** (`finops-check.yml` + `scripts/finops_issue.py`): exactly one issue titled `TITLE` ("Azure waste report") whose body contains `MARKER`; above `--threshold` create/update, "zero" (`summary.count == 0` and total 0, i.e. no paid or unpriced finding) closes, in between only an open issue is updated. The previous report comes from the newest unexpired `finops-report` artifact of a `main` run (`gh api .../actions/artifacts?name=finops-report`); exit code 2 with `--previous` (e.g. other currency) retries once without the trend. Body text is English (it is a repo notification), the report itself stays German.
- **Azure DevOps** (`azure-pipelines.yml`): cannot be run or validated against Azure DevOps here; CI parses it (`lint` job) and `tests/test_azure_pipelines.py` pins its shape (weekly on main, AzureCLI@2 with the compile-time service connection, same artifact name for download and publish, no terraform). Parameters reach the inline script through `env:`, not by `${{ }}` inside the script. Keep it in step with `finops-check.yml` when the finder's flags change.
- **Live E2E** (`e2e.yml`): the only workflow that creates resources, so `workflow_dispatch` only (asserted by `tests/test_workflows.py`), environment `azure-e2e`, unique `TF_VAR_prefix=e2e-<run_id>-<attempt>`, local state inside the job, `terraform destroy` as last step with `if: always() && steps.init.outcome == 'success'`. It deploys into the existing group from `infra/github-oidc` (`TF_VAR_resource_group_name`), so it needs `ARM_RESOURCE_PROVIDER_REGISTRATIONS=none` (Contributor on one group cannot register providers), `TF_VAR_enable_budget=false` and no extra waste (the empty resource group needs subscription rights). Never run it here: no credentials exist (D2). Changing the base resources' names in `infra/` means updating `expected_findings` and `BASE_RULES`.
- **Azure Workbook** (`scripts/build_workbook.py`, `workbooks/`, `infra/workbook.tf`): the workbook is generated, so change the registry or the KQL file and regenerate, never edit the JSON. The tail added to each KQL file mirrors what the CLI does in Python (ignore tag via `tolower(tostring(tags)) !contains '"waste-finder:ignore":"true"'`, `isnull(ageDays) or ageDays >= {Parameter}`); `exclude` patterns and prices are CLI-only. Workbook text is German like the report. Resource Graph allows only a few `union`/`join`s per query, so there is no combined overview query. The Terraform resource is opt-in (`enable_workbook`, default false) and free; its tests compare `data_json` with `file()` of the generated workbook. Not validated against a live portal here (D2); the JSON follows the Notebook/1.0 format of the Azure Workbooks gallery templates.
- **OIDC identity** (`infra/github-oidc/`): least privilege is asserted in its tests (subscription roles exactly Reader + Cost Management Reader; Contributor only with `enable_e2e` and only on the E2E group). Never widen it to Contributor on the subscription: the scheduled check shares the identity and must stay read-only. A new workflow that logs in to Azure needs a matching subject (a job on `main` without environment, or `environment: azure-e2e`), `permissions: id-token: write` and a job-level `if: vars.AZURE_CLIENT_ID != ''`. Mocked IDs must be well-formed (`/applications/<uuid>`, `/subscriptions/<uuid>`), hence `mock_resource`/`mock_data` defaults with `override_during = plan`. `terraform init` creates `.terraform.lock.hcl` files; they are not tracked.

## CI

`.github/workflows/ci.yml` runs on PRs and pushes to `main`: job `lint` (`ruff check`, `ruff format --check`, `mypy`, `azure-pipelines.yml` parses with PyYAML), job `actionlint` (`docker://rhysd/actionlint`, shellcheck included, `-ignore SC2086:info` because existing steps expand fixed values unquoted; new shell steps quote their variables), job `audit` (`pip-audit` on `pip freeze --exclude-editable` of the installed `.[dev]` env, so the runner's own pip/setuptools are not audited; fails on any known vulnerability, fix by raising the lower bound in `pyproject.toml`), job `python` (pytest with coverage on 3.11 / 3.12 / 3.13, floor = `fail_under` in `pyproject.toml`; JUnit results published by `dorny/test-reporter`, skipped for Dependabot/fork PRs whose token cannot create check runs; artifacts `coverage-<version>` and, from 3.12, `demo-report` with all five formats and the summary on the run page) job `terraform` (matrix over the Terraform roots `infra` and `infra/github-oidc`: `fmt -check`, `init -backend=false`, `validate`, `terraform test`, `tflint`; a new root is added to the matrix and gets its own `.tflint.hcl` and `tests/`) and job `config-scan` (Checkov on `infra/`, `--soft-fail`, SARIF uploaded to the Security tab, upload skipped for Dependabot/fork PRs). Intentional Checkov findings are skipped inline (`#checkov:skip=ID:reason`) in the resource block; fix real findings instead of skipping them. New Terraform resources get assertions in `infra/tests/`; when an assertion needs a value that is only known after apply (an ID), use `override_resource` with `override_during = plan` instead of `command = apply` (mocked IDs fail azurerm's ID validation). Coverage floor per D7: measured value rounded down to 5, never below 80; raise it when coverage grows, never lower it to get green. Job `docker` (in `ci.yml`) builds the image without pushing, checks uid 10001 and runs `--version` and the demo with a mounted output directory (`--user $(id -u):$(id -g)`). `.github/workflows/cd.yml` (D9) runs on `workflow_run` of CI, only for a successful `push` run on `main`, checks out `workflow_run.head_sha`, gets the version from `python -m setuptools_scm`, builds, smoke-tests and pushes `ghcr.io/viache25/azure-waste-finder:<short sha>` and `:latest` with `GITHUB_TOKEN` (`packages: write`), then runs Trivy (`aquasecurity/trivy-action` pinned to a commit SHA, `continue-on-error`, `ignore-unfixed`) on the local image and uploads SARIF (category `trivy-image`, `sha`/`ref` of the tested commit). Edits to `cd.yml` only take effect after merge; watch the CD run on `main` (`gh run list -w CD`). `.github/workflows/pages.yml` (D9, same trigger and `head_sha` checkout) builds `waste-finder --demo --format html,json,md,csv` into `site/` (`index.html` = report.html, plus `report.schema.json`) and deploys it with `actions/upload-pages-artifact` + `actions/deploy-pages` (environment `github-pages`, `pages: write`, `id-token: write`) to https://viache25.github.io/azure-waste-finder/; Pages source is "GitHub Actions" (`build_type=workflow`). Only demo data is ever published. Job `package` (in `ci.yml`) builds sdist + wheel with `fetch-depth: 0` (setuptools-scm needs the tags), runs `twine check --strict` and the demo from the installed wheel outside the source tree. Versions come from git tags via setuptools-scm (`dynamic = ["version"]`; `waste_finder.__version__` reads the installed package metadata, `0.0.0+unknown` for an uninstalled tree); there is no version string to bump in the code. `.github/workflows/release.yml` runs on tags `v*`: build (version must equal the tag) → `test-wheel` (3.11–3.13, `src/` removed, full pytest against the installed wheel, demo) → `github-release` (`gh release create --generate-notes --verify-tag`, wheel + sdist attached, `-` in the tag = pre-release) and `pypi` (trusted publishing via `pypa/gh-action-pypi-publish`, environment `pypi`, only when repo variable `PYPI_PUBLISH == 'true'`). Release = `git tag -a vX.Y.Z -m vX.Y.Z && git push origin vX.Y.Z` on `main`; if the release job fails before the release exists, delete and re-push the tag after the fix is merged. `.github/workflows/codeql.yml` runs CodeQL (Python, default query suite, `build-mode: none`) on PRs, `main` and weekly; results go to the Security tab. Vulnerability reporting and scope: `SECURITY.md`. `.github/workflows/finops-check.yml` (D2) runs weekly (Mon 06:17 UTC) + `workflow_dispatch` (input `threshold`): job `check` only `if: vars.AZURE_CLIENT_ID != ''`, no environment (branch subject), permissions `contents: read`, `id-token: write`, `issues: write`, `actions: read`; `azure/login@v3` → previous `finops-report` artifact → `waste-finder --subscription $AZURE_SUBSCRIPTION_ID --cost-source ${FINOPS_COST_SOURCE:-retail} --format md,html,json --summary $GITHUB_STEP_SUMMARY [--previous]` → artifact `finops-report` (90 days) → `scripts/finops_issue.py` (threshold: input, else `vars.FINOPS_ISSUE_THRESHOLD`, else 10). Unconfigured it is skipped; check with `gh workflow run finops-check.yml` and `gh run view` (job `check` skipped, run green). `.github/workflows/e2e.yml` (D3) is `workflow_dispatch` only, job `e2e` with `if: vars.AZURE_CLIENT_ID != ''` and `environment: azure-e2e`: `azure/login@v3` + `ARM_USE_OIDC` → `terraform init/apply` in `infra/` → `scripts/stop-vm.sh` → `waste-finder --format json` + `scripts/e2e_assert.py` (10 attempts, 60 s apart, Resource Graph lag) → artifact `e2e-report` → `terraform destroy` (always). README "Live end-to-end test" has the cost per run (~0.02 €).

Dependabot (`.github/dependabot.yml`) opens weekly PRs for pip, GitHub Actions, Terraform providers (both roots) and the Docker base image (digest updates; Python minor/major bumps of the image are ignored on purpose): minor + patch bumps grouped into one PR per ecosystem, each major bump as its own PR. Merge policy: squash-merge a Dependabot PR once CI is green; a major bump that fails CI is fixed on its branch if the fix is small and in scope, otherwise closed with a one-line reason; if a merged bump makes a statement in CLAUDE.md, README.md or the Stack line of issue #1 stale, fix it.
