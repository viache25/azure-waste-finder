# 0002. List prices by default, actual costs on request

- **Status:** Accepted
- **Date:** 2026-10-04 (actual costs added; list prices since v0.1)

## Context

A finding needs a euro amount, or the report cannot say "Sie verlieren ca. X € pro Monat". There are two sources:

- the public **Azure Retail Prices API**: no login, several currencies, list prices per meter;
- the **Cost Management Query API**: what a resource really cost, including EA/CSP discounts, reservations and savings plans. It needs the Cost Management Reader role, lags up to a day, and has no data for resources younger than a day.

## Decision

- **Default `--cost-source retail`**: each rule names a pricing strategy that turns a finding into an hourly or per-GB list price from the Retail Prices API (EUR unless `currency` is set). Monthly = hourly × 730, the pricing calculator's convention. Price lists are cached for 24 h.
- **Opt-in `--cost-source actual`**: one Cost Management query per subscription that has findings, `AmortizedCost` of the last 30 full days grouped by resource ID. The 30-day sum is the monthly amount.
- **Per-finding fallback**: a finding keeps its list price when Cost Management has no row for it, the row is in another currency, or its subscription's query failed (with a warning). A downgrade keeps the retail ratio of savings to cost.
- **The report says where each number comes from**: a "Quelle" column in actual runs, a footer explaining list prices, and `cost_source` per finding in JSON, CSV and SARIF.

## Consequences

- The demo, CI and every first run work without cost-data permissions or billing access.
- List prices can overstate the waste of a discounted customer; the report says so in its footer. Actual costs fix that where they exist, and a mixed report stays honest because the source is shown per finding.
- Some resources cannot be priced from list prices (e.g. StandardV2 NAT gateways, Elastic Premium plans); they stay unpriced and are counted, not guessed.
- Trends compare like with like: a previous report with another cost source adds a note, another currency is an error.

## Alternatives considered

- **Actual costs only**: needs Cost Management Reader and billing data from the first run, says nothing about resources younger than a day, and cannot run offline or in the demo.
- **The Azure pricing calculator or hard-coded prices**: no API, and prices drift.
- **Scaling the actual 30-day sum to 730 h**: rejected; the amortized sum already is the monthly bill, and scaling would invent precision.
