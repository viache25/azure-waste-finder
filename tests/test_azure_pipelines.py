"""azure-pipelines.yml (the Azure DevOps version of finops-check.yml) parses and keeps its shape.

It never runs in GitHub; these checks are what CI can verify without an Azure DevOps organization."""

from pathlib import Path

import pytest
import yaml

PIPELINE = Path(__file__).resolve().parent.parent / "azure-pipelines.yml"


@pytest.fixture(scope="module")
def pipeline():
    return yaml.safe_load(PIPELINE.read_text(encoding="utf-8"))


def tasks(pipeline, name):
    return [step for step in pipeline["steps"] if step.get("task") == name]


def test_runs_weekly_on_main_only(pipeline):
    assert pipeline["trigger"] == "none" and pipeline["pr"] == "none"  # no CI runs on pushes or PRs
    (schedule,) = pipeline["schedules"]
    _minute, _hour, day_of_month, month, day_of_week = schedule["cron"].split()
    assert (day_of_month, month, day_of_week) == ("*", "*", "1")  # once a week, Monday
    assert schedule["branches"]["include"] == ["main"]
    assert schedule["always"] is True


def test_logs_in_with_the_service_connection(pipeline):
    (cli,) = tasks(pipeline, "AzureCLI@2")
    variables = {v["name"]: v["value"] for v in pipeline["variables"]}
    assert variables["azureServiceConnection"] == "azure-waste-finder"
    # Service connections must be known at compile time: a template expression, not a $(macro).
    assert cli["inputs"]["azureSubscription"] == "${{ variables.azureServiceConnection }}"
    assert cli["inputs"]["scriptType"] == "bash"


def test_runs_the_finder_like_the_github_workflow(pipeline):
    (cli,) = tasks(pipeline, "AzureCLI@2")
    script = cli["inputs"]["inlineScript"]
    assert "waste-finder" in script
    assert '--format "md,html,json"' in script
    assert '--summary "$REPORT_DIR/summary.md"' in script
    assert '--previous "$PREVIOUS_REPORT"' in script
    assert "--fail-over" in script
    assert "terraform" not in PIPELINE.read_text(encoding="utf-8")  # read-only, safe on a schedule (D3)
    assert cli["env"]["COST_SOURCE"] == "${{ parameters.costSource }}"  # parameters reach the script via env


def test_parameters(pipeline):
    params = {p["name"]: p for p in pipeline["parameters"]}
    assert params["costSource"]["default"] == "retail"
    assert params["costSource"]["values"] == ["retail", "actual"]
    assert params["failOver"]["default"].strip() == ""  # never fails unless asked to


def test_previous_report_and_artifact_use_the_same_name(pipeline):
    (download,) = tasks(pipeline, "DownloadPipelineArtifact@2")
    (publish,) = tasks(pipeline, "PublishPipelineArtifact@1")
    assert download["inputs"]["artifact"] == publish["inputs"]["artifact"] == "finops-report"
    assert download["continueOnError"] is True  # the first run has nothing to download
    assert download["inputs"]["runVersion"] == "latestFromBranch"
    assert download["inputs"]["pipeline"] == "$(System.DefinitionId)"
    assert publish["condition"] == "succeededOrFailed()"  # also published when --fail-over fails the run


def test_checkout_fetches_tags_for_the_version(pipeline):
    checkout = pipeline["steps"][0]
    assert checkout["checkout"] == "self" and checkout["fetchDepth"] == 0 and checkout["fetchTags"] is True
