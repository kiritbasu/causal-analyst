"""The scripts also import as the `causal_analyst` package (used by downstream libraries)."""
import importlib.util
import zipfile
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.skipif(importlib.util.find_spec("causal_analyst") is None, reason="package not installed")
def test_package_imports_without_path_hacks():
    code = (
        "import sys, causal_analyst.ca as ca, causal_analyst.ca_checks as ck;"
        "from causal_analyst import ca_core;"
        "assert ca.core is ca_core and ck.core is ca_core;"
        "assert 'ca_core' not in sys.modules, 'top-level ca_core leaked';"
        "print(ca._sibling('ca_dag').__name__)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "causal_analyst.ca_dag"


GEN = Path(__file__).resolve().parents[1] / "skills" / "causal-data-generator"


def test_generator_builds_as_its_own_package(tmp_path):
    """The generator ships as `causal_data_generator`, scenarios included, separate from the analyst."""
    pytest.importorskip("hatchling")
    subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "-w", str(tmp_path), str(GEN)],
                   check=True, capture_output=True)
    whl = next(tmp_path.glob("causal_data_generator-*.whl"))
    names = zipfile.ZipFile(whl).namelist()
    assert "causal_data_generator/cg_engine.py" in names
    assert "causal_data_generator/scenarios/sales-calls.json" in names
    assert not any(n.startswith("causal_analyst/") for n in names)


def test_generator_package_loads_scenarios_from_source_tree():
    sys.path.insert(0, str(GEN))
    try:
        spec = importlib.util.spec_from_file_location("causal_data_generator", GEN / "scripts" / "__init__.py",
                                                      submodule_search_locations=[str(GEN / "scripts")])
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(GEN))
    assert "sales-calls" in mod.scenario_ids()
    assert mod.scenario("sales-calls")["id"] == "sales-calls"
    with pytest.raises(KeyError):
        mod.scenario("no-such-scenario")
