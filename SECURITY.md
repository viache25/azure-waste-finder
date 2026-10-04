# Security policy

## Supported versions

Only the latest release and the latest commit on `main` are supported. There are no maintained release branches;
fixes ship in the next release.

## Reporting a vulnerability

Please do not open a public issue. Report it privately through GitHub instead:
**Security → Report a vulnerability** on this repository (private vulnerability reporting).

Include what is affected (file, command, workflow), how to reproduce it and the impact you expect.
You should get a first answer within a week. Once a fix is merged, the advisory is published with credit,
unless you prefer to stay anonymous.

## Scope and design

- The CLI is **read-only** against Azure: it runs Resource Graph queries, reads the public Retail Prices API and,
  with `--cost-source actual`, queries Cost Management.
  It never creates, changes or deletes resources. A code path that writes to Azure is a bug and in scope.
- Authentication is `DefaultAzureCredential` only (e.g. `az login`). No keys, secrets or tokens belong in the code,
  tests, fixtures or workflows; CI runs without any Azure credentials.
- `infra/` is a **deliberately wasteful** demo environment. Wasted money is the point, not a vulnerability.
  Intentional Checkov findings are skipped inline with a reason; anything that exposes the environment
  (public access, password login, leaked state) is in scope.
- `*.tfstate` and `*.tfvars` are git-ignored because state contains the generated SSH key.

## Automated checks

| Check | Where |
|---|---|
| CodeQL (Python) | `.github/workflows/codeql.yml`, on PRs, `main` and weekly; results in the Security tab |
| `pip-audit` on runtime and dev dependencies | `audit` job in `.github/workflows/ci.yml`, fails on known vulnerabilities |
| Checkov on `infra/` | `config-scan` job in `.github/workflows/ci.yml`, report-only SARIF in the Security tab |
| Dependency updates | Dependabot, weekly, for pip, GitHub Actions and Terraform providers |
| Release artifacts | `.github/workflows/release.yml` tests the built wheel before it is attached to a GitHub Release; PyPI publishing uses trusted publishing (no stored token) |
