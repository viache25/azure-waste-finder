"""Static checks of the GitHub workflows: they parse, Azure jobs skip when not configured (D2), and nothing that
creates Azure resources runs on a schedule (D3)."""

from pathlib import Path

import pytest
import yaml

import finops_issue

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
AZURE_GUARD = "vars.AZURE_CLIENT_ID != ''"


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def triggers(workflow):
    # YAML 1.1 reads the key `on` as the boolean True.
    on = workflow.get("on", workflow.get(True))
    return {on} if isinstance(on, str) else set(on)


def steps(job):
    return job.get("steps", [])


def uses_azure(job):
    return any(str(step.get("uses", "")).startswith("azure/login@") for step in steps(job))


def run_text(job):
    return "\n".join(str(step.get("run", "")) for step in steps(job))


def test_there_are_workflows():
    assert {p.name for p in WORKFLOWS} >= {"ci.yml", "finops-check.yml"}


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_parses(path):
    workflow = load(path)
    assert workflow["name"] and triggers(workflow) and workflow["jobs"]


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_azure_jobs_skip_when_not_configured(path):
    for name, job in load(path)["jobs"].items():
        if uses_azure(job):
            assert AZURE_GUARD in str(job.get("if", "")), f"{path.name}:{name} must skip without AZURE_CLIENT_ID"
            assert job["permissions"]["id-token"] == "write", f"{path.name}:{name} needs id-token: write for OIDC"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_nothing_that_creates_resources_is_scheduled(path):
    workflow = load(path)
    creates = any("terraform apply" in run_text(job) for job in workflow["jobs"].values())
    if creates:
        assert triggers(workflow) == {"workflow_dispatch"}, f"{path.name} creates Azure resources: manual runs only"


def test_finops_check():
    workflow = load(ROOT / ".github" / "workflows" / "finops-check.yml")
    assert triggers(workflow) == {"schedule", "workflow_dispatch"}
    job = workflow["jobs"]["check"]
    assert job["if"] == AZURE_GUARD
    assert uses_azure(job)
    assert job["permissions"] == {"contents": "read", "id-token": "write", "issues": "write", "actions": "read"}
    assert "environment" not in job  # logs in with the branch credential (refs/heads/main), read-only
    script = run_text(job)
    assert '--format "md,html,json"' in script
    assert '--summary "$GITHUB_STEP_SUMMARY"' in script
    assert '--previous "$PREVIOUS"' in script
    assert "terraform" not in script
    upload = next(s for s in steps(job) if str(s.get("uses", "")).startswith("actions/upload-artifact@"))
    assert upload["with"]["name"] == finops_issue.ARTIFACT  # the issue body points to this artifact
    assert "python scripts/finops_issue.py --report reports/report.json" in script


def test_e2e_is_manual_and_always_cleans_up():
    workflow = load(ROOT / ".github" / "workflows" / "e2e.yml")
    assert triggers(workflow) == {"workflow_dispatch"}  # creates resources: never on a schedule (D3)
    job = workflow["jobs"]["e2e"]
    assert job["if"] == AZURE_GUARD
    assert job["environment"] == "azure-e2e"  # required reviewer + the environment federated credential
    assert job["permissions"] == {"contents": "read", "id-token": "write"}
    assert "github.run_id" in job["env"]["TF_VAR_prefix"]  # unique prefix per run
    assert job["env"]["ARM_RESOURCE_PROVIDER_REGISTRATIONS"] == "none"
    assert job["env"]["TF_VAR_enable_budget"] == "false"

    runs = [str(step.get("run", "")) for step in steps(job)]

    def index(text):
        return next(i for i, run in enumerate(runs) if text in run)

    assert index("terraform apply") < index("scripts/stop-vm.sh") < index("waste-finder") < index("terraform destroy")
    finder = runs[index("waste-finder")]
    assert "--format json" in finder and "scripts/e2e_assert.py" in finder
    destroy = steps(job)[index("terraform destroy")]
    assert destroy is steps(job)[-1]
    assert "always()" in destroy["if"]  # also after a failed assertion, a failed apply or a cancel
