"""analyse(df, spec) gives the same answer as `ca.py run`, without touching files."""
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "causal-analyst" / "scripts"
EX = ROOT / "examples" / "loyalty-program"


@pytest.mark.slow
def test_analyse_matches_cli(tmp_path):
    spec = json.loads((EX / "spec.json").read_text())
    spec.update(data=str(EX / "data.csv"), budget="quick", causalpfn_max_rows=0)
    spec.pop("allow_external_services", None)
    (tmp_path / "spec.json").write_text(json.dumps(spec))
    subprocess.run([sys.executable, str(SCRIPTS / "ca.py"), "run", "spec.json", "--out", "results.json"],
                   cwd=tmp_path, check=True, capture_output=True, text=True)
    cli = json.loads((tmp_path / "results.json").read_text())

    sys.path.insert(0, str(SCRIPTS))
    try:
        import ca
    finally:
        sys.path.remove(str(SCRIPTS))
    no_path = {k: v for k, v in spec.items() if k != "data"}
    lib = json.loads(json.dumps(ca.analyse(pd.read_csv(EX / "data.csv"), no_path), default=ca._json))
    assert "data" not in no_path, "analyse must not change the caller's spec"

    assert lib["main_method"] == cli["main_method"]
    assert lib["main_result"]["estimate"] == pytest.approx(cli["main_result"]["estimate"], rel=1e-9)
    assert lib["main_result"]["ci"] == pytest.approx(cli["main_result"]["ci"], rel=1e-9)
    assert lib["trust_tier"] == cli["trust_tier"]
    assert lib["trust_reasons"] == cli["trust_reasons"]
    assert lib["manifest"]["fingerprint"] is None and cli["manifest"]["fingerprint"].startswith("ds-")
