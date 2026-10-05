# Architecture decision records

Short records of the decisions that shape Azure Waste Finder: the context, the decision, and what follows from it. The step-by-step plan and the smaller working decisions (D1–D12) are in [issue #1](https://github.com/viache25/azure-waste-finder/issues/1).

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-resource-graph.md) | Find waste with Azure Resource Graph (one KQL query per rule) | Accepted |
| [0002](0002-retail-vs-actual-costs.md) | List prices by default, actual costs from Cost Management on request, with a per-finding fallback | Accepted |
| [0003](0003-rules-as-data.md) | Rules are data: a registry entry plus a KQL file, pricing strategies by name | Accepted |
| [0004](0004-oidc-only-auth.md) | Automation authenticates with OIDC federation only: no client secrets, no API tokens | Accepted |

New ADR: copy the structure of an existing one (Status, Context, Decision, Consequences, Alternatives), take the next number, and add it to this table. An ADR is not edited once accepted; a new one supersedes it.
