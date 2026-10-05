# 0001. Find waste with Azure Resource Graph

- **Status:** Accepted
- **Date:** 2026-09-20 (v0.1)

## Context

The tool must find idle resources of many types (disks, VMs, public IPs, snapshots, App Service plans, NAT gateways, load balancers, NICs, NSGs, resource groups), in one or many subscriptions, with read-only access. Each resource provider has its own management API and SDK client, and some facts (a VM's power state, a disk's attachment state) are spread across them.

## Decision

Every rule is **one Azure Resource Graph query** (`src/waste_finder/queries/<rule>.kql`) that returns exactly the wasteful resources. `rules.py` runs it over the chosen scope (given subscriptions, a management group, or every subscription the credential can read), pages through the results and turns each row into a `Finding`. The query runner is an injected function (`Callable[[str], list[dict]]`), so tests and `--demo` run the same code on recorded rows.

## Consequences

- One query language and one API call per rule for all resource types and all subscriptions; fast even in large tenants, and **Reader** is enough.
- A rule's logic is visible and testable as text. The same KQL files feed the generated [Azure Workbook](../../workbooks/waste-finder.workbook.json), so the portal view and the CLI cannot disagree.
- Resource Graph's KQL is a subset: no anti-join (empty resource groups use a left outer join on a count), no `mv-apply` (`mv-expand` + `summarize` instead), and only a few `join`/`union` per query, so there is no single "all rules" query.
- Resource Graph is eventually consistent: new resources and power-state changes show up with a delay of seconds to minutes. The live end-to-end test retries for that reason.
- Some facts are not in Resource Graph at all: the used size of a snapshot (priced at the provisioned size, an upper bound), traffic or CPU history. Rules that need metrics are out of scope for now.

## Alternatives considered

- **Per-service SDK clients** (Compute, Network, Web …): one client and one listing per resource type and subscription, many more calls, and the filtering moves into Python.
- **Azure Advisor cost recommendations**: useful, but a fixed rule set with its own refresh cycle; it cannot be extended with new rules, priced in a chosen currency, or tested offline.
- **Azure Policy (audit)**: needs policy assignments in the customer's tenant, which a read-only check should not require.
