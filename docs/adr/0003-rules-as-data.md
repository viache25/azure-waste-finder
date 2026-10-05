# 0003. Rules are data

- **Status:** Accepted
- **Date:** 2026-10-01

## Context

v0.1 had three rules, with their titles, prices and remediation text spread over the query runner, the pricing module, the templates and the CLI. The plan added eight more. Adding a rule should not mean editing five files and hoping the report, the exporters and the CLI agree.

## Decision

A rule is **one `Rule` entry in `registry.py` plus one KQL file**:

- the entry holds the id, German and English title, severity, KQL file name, pricing strategy name, German "why" and "action" texts, the `az` command template and a learn.microsoft.com docs link;
- pricing strategies are plain functions in `pricing.STRATEGIES`, looked up by name; several rules can share one (`free` for the clean-up rules);
- the report templates, the JSON/CSV/SARIF exporters, the CLI and the Azure Workbook generator read everything from the registry.

Tests enforce completeness: every entry has its KQL file, its strategy and demo rows, there are no unused KQL files or strategies, and the generated workbook is in sync.

## Consequences

- A new rule is a checklist (CLAUDE.md "How to add a rule"): KQL file, registry entry, pricing, demo rows, tests, README row, regenerated workbook. No template or exporter changes.
- Remediation stays text (D5): the tool prints the exact `az` command and never runs it.
- Rules with special needs get them as data, too: `quantity_unit_de`, `age_label_de`, and the age-based minimum in `Settings.min_age_days`.
- Logic that is not a query or a price (ignore tag, thresholds, trends) stays in shared code and applies to all rules alike.

## Alternatives considered

- **A class per rule (plugin pattern)**: more ceremony per rule, and behaviour hides in overrides; the rules differ only in data and in their price function.
- **Rule definitions in YAML**: a second format to validate, and the pricing still needs Python; a frozen dataclass gives type checking (mypy strict) for free.
