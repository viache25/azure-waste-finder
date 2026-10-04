import importlib.metadata
import json
import runpy
import sys

import pytest

import waste_finder
from waste_finder.cli import main


def test_version_comes_from_the_installed_package():
    # setuptools-scm writes the git-tag version into the package metadata at build/install time.
    assert waste_finder.__version__ == importlib.metadata.version("azure-waste-finder")


def test_version_of_an_uninstalled_source_tree(monkeypatch):
    def not_installed(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(waste_finder, "version", not_installed)
    assert waste_finder._installed_version() == "0.0.0+unknown"


def test_cli_version_flag(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out == f"waste-finder {waste_finder.__version__}\n"


def test_reports_carry_the_version(tmp_path):
    assert main(["--demo", "--format", "json,sarif", "--out-dir", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    sarif = json.loads((tmp_path / "report.sarif").read_text(encoding="utf-8"))
    assert report["tool"]["version"] == sarif["runs"][0]["tool"]["driver"]["version"] == waste_finder.__version__


def test_python_m_entry_point(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["waste_finder", "--demo", "--out-dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("waste_finder", run_name="__main__")
    assert exit_info.value.code == 0
    assert (tmp_path / "report.html").exists()
