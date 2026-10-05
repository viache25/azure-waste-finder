# 0004. OIDC federation only: no secrets in automation

- **Status:** Accepted
- **Date:** 2026-10-05

## Context

Several automated jobs need credentials: the weekly FinOps check reads a real subscription, the manual end-to-end test deploys and destroys the demo waste, the Azure DevOps pipeline does the same check, images go to GHCR, and releases may go to PyPI. Long-lived secrets (client secrets, API tokens) would have to be created, stored, rotated and could leak through logs or forks.

## Decision

Every automated login uses **short-lived tokens through OpenID Connect federation**; no client secret, certificate or API token exists anywhere:

- **GitHub Actions → Azure**: an Entra app registration with federated credentials (Terraform in `infra/github-oidc/`, applied once by the owner). Only two subjects are trusted: runs on `main` without an environment (the scheduled check) and jobs in the GitHub environment `azure-e2e` (the end-to-end test, with a required reviewer).
- **Least privilege**: Reader + Cost Management Reader on the subscription; Contributor only on the one E2E resource group, and only with `enable_e2e`. The Terraform tests assert exactly this.
- **Azure DevOps → Azure**: a service connection with workload identity federation, which can reuse the same read-only app.
- **GitHub → GHCR** with the job's `GITHUB_TOKEN`; **PyPI** with trusted publishing (prepared, off until the owner enables it).
- **Locally**: `DefaultAzureCredential`, i.e. the user's `az login`.

Repository variables hold only IDs (client, tenant, subscription). Until they are set, every Azure job skips (`if: vars.AZURE_CLIENT_ID != ''`), so CI stays green without Azure; `tests/test_workflows.py` asserts the guard and `id-token: write` on every job that logs in.

## Consequences

- Nothing to rotate or leak: a token lives for one job and is bound to the repository, branch or environment.
- The one-time setup (applying `infra/github-oidc`, setting the variables, creating the `azure-e2e` environment) is an owner action; the code cannot do it.
- A new workflow that logs in needs a matching subject (a job on `main` without environment, or `environment: azure-e2e`). Pull requests and forks cannot log in to Azure at all, which is intended.
- The scheduled check shares the identity, so the identity must stay read-only: never widen it to Contributor on the subscription.

## Alternatives considered

- **Client secret in GitHub secrets**: simple, but long-lived, needs rotation and is a standing leak risk.
- **Certificate credential**: the same rotation problem.
- **Self-hosted runner with a managed identity**: no secret either, but a VM that costs money around the clock and needs patching, against D3 and D12.
