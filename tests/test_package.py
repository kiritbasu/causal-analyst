"""The scripts also import as the `causal_analyst` package (used by downstream libraries)."""
import importlib.util
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
