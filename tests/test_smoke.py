import runpy
import sys

import pytest

import waste_finder


def test_version():
    assert waste_finder.__version__ == "0.1.0"


def test_python_m_entry_point(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["waste_finder", "--demo", "--out-dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("waste_finder", run_name="__main__")
    assert exit_info.value.code == 0
    assert (tmp_path / "report.html").exists()
