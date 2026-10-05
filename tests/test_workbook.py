"""scripts/build_workbook.py: the Azure Workbook is generated from the registry and the KQL files and stays in sync."""

import json
import runpy
import sys
import uuid
from pathlib import Path

import pytest

import build_workbook
from build_workbook import (
    AGE_PARAMETERS,
    RESOURCE_GRAPH,
    WORKBOOK,
    kql_command,
    main,
    render,
    workbook_query,
)
from waste_finder.config import Settings
from waste_finder.registry import REGISTRY
from waste_finder.rules import load_query

ROOT = Path(__file__).resolve().parent.parent
build = build_workbook.build_workbook
IGNORE_FILTER = '| where tolower(tostring(tags)) !contains \'"waste-finder:ignore":"true"\''


def queries(workbook):
    return {item["name"].removeprefix("query - "): item["content"] for item in workbook["items"] if item["type"] == 3}


def test_committed_workbook_is_in_sync():
    """Fails when a rule or KQL file changed without `python scripts/build_workbook.py`."""
    assert WORKBOOK == ROOT / "workbooks" / "waste-finder.workbook.json"
    assert WORKBOOK.read_text(encoding="utf-8") == render(), "run: python scripts/build_workbook.py"


def test_render_is_deterministic_json():
    assert render() == render()
    workbook = json.loads(render())
    assert workbook["version"] == "Notebook/1.0"
    assert workbook["fallbackResourceIds"] == ["azure monitor"]
    names = [item["name"] for item in workbook["items"]]
    assert len(names) == len(set(names)), "workbook item names must be unique"


def test_one_resource_graph_query_per_rule():
    items = queries(build())
    assert list(items) == [r.id for r in REGISTRY.values() if r.pricing != "free"] + [
        r.id for r in REGISTRY.values() if r.pricing == "free"
    ]
    for content in items.values():
        assert content["queryType"] == 1 and content["resourceType"] == RESOURCE_GRAPH
        assert content["crossComponentResources"] == ["{Subscription}"]
        assert content["visualization"] == "table"


@pytest.mark.parametrize("rule", REGISTRY.values(), ids=list(REGISTRY))
def test_query_is_the_kql_file_plus_a_tail(rule):
    query = queries(build())[rule.id]["query"]
    kql = load_query(rule.id).rstrip("\n")
    assert query.startswith(kql + "\n"), "the workbook must run the KQL file unchanged"
    tail = query.removeprefix(kql + "\n").splitlines()
    assert tail[0] == IGNORE_FILTER
    assert tail[-1] == f"| extend command = {kql_command(rule.command)}"
    if rule.id in AGE_PARAMETERS:
        assert tail[1] == f"| where isnull(ageDays) or ageDays >= {{{AGE_PARAMETERS[rule.id][0]}}}"
        assert len(tail) == 3
    else:
        assert len(tail) == 2


def test_rule_text_comes_from_the_registry():
    texts = {item["name"]: item["content"]["json"] for item in build()["items"] if item["type"] == 1}
    for rule in REGISTRY.values():
        text = texts[f"text - {rule.id}"]
        assert rule.title_de in text and rule.why_de in text and rule.action_de in text and rule.docs_url in text
    assert texts["text - cleanup"].startswith("## Aufräumen (kostenlos)")
    free = [r for r in REGISTRY.values() if r.pricing == "free"]
    assert all(texts[f"text - {r.id}"].startswith("### ") for r in free)


def test_parameters_match_the_cli_defaults():
    parameters = next(item for item in build()["items"] if item["type"] == 9)["content"]["parameters"]
    by_name = {p["name"]: p for p in parameters}
    assert by_name["Subscription"]["type"] == 6 and by_name["Subscription"]["multiSelect"] is True
    assert by_name["Subscription"]["defaultValue"] == "value::all"
    assert set(AGE_PARAMETERS) == set(Settings().min_age_days), "every age-based rule needs a workbook parameter"
    for rule_id, (name, _label) in AGE_PARAMETERS.items():
        assert by_name[name]["value"] == str(Settings().min_age_days[rule_id])
    for parameter in parameters:
        assert uuid.UUID(parameter["id"])


def test_workbook_query_without_age_filter():
    query = workbook_query(REGISTRY["stopped_vm"])
    assert "ageDays" not in query
    assert query.endswith("| extend command = strcat('az vm deallocate --ids ', id)")


def test_kql_command():
    assert kql_command("az disk delete --ids {id}") == "strcat('az disk delete --ids ', id)"
    assert kql_command("az group delete --name {name} --subscription {subscription}") == (
        "strcat('az group delete --name ', name, ' --subscription ', tostring(split(id, '/')[2]))"
    )
    assert kql_command("{id}") == "strcat(id)"
    assert kql_command("echo 'x' \\ {id}") == "strcat('echo \\'x\\' \\\\ ', id)"
    with pytest.raises(ValueError, match="unknown placeholder"):
        kql_command("az thing --rg {resource_group}")


def test_main_writes_and_checks(tmp_path, capsys):
    out = tmp_path / "sub" / "workbook.json"
    assert main(["--check", "--output", str(out)]) == 1  # missing file
    assert "out of date" in capsys.readouterr().err
    assert main(["--output", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == render()
    assert main(["--check", "--output", str(out)]) == 0
    assert "up to date" in capsys.readouterr().out
    out.write_text("{}\n", encoding="utf-8")
    assert main(["--check", "--output", str(out)]) == 1


def test_check_of_the_committed_file():
    assert main(["--check"]) == 0


def test_runs_as_a_script(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["build_workbook.py", "--output", str(tmp_path / "w.json")])
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(build_workbook.__file__, run_name="__main__")
    assert exit_info.value.code == 0
    assert (tmp_path / "w.json").is_file()
