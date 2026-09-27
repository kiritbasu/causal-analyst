"""Generator: every ready-made scenario generates at its default level, the truth is recovered by a
correct adjustment at Starter, traps bite, and blind mode hides the truth."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
G = ROOT / "skills" / "causal-data-generator"
sys.path.insert(0, str(G / "scripts"))
import cg_engine as E  # noqa: E402

SCN = sorted((G / "scenarios").glob("*.json"))


@pytest.mark.parametrize("path", SCN, ids=[p.stem for p in SCN])
def test_default_level(path):
    scn = json.loads(path.read_text())
    n = min(int(scn["n"]), 4000) if scn["design"] != "rollout" else None
    df, brief, key = E.generate(scn, scn.get("default_level", "realistic"), None, 7, n)
    assert len(df) > 0 and "## Columns" in brief
    assert key["targets"] and key["methods"]
    assert scn["outcome"]["name"] in df.columns or scn["outcome"].get("cryptic") in df.columns


def test_starter_linear_recovers_truth():
    scn = json.loads((G / "scenarios" / "retail-loyalty.json").read_text())
    df, _, key = E.generate(scn, "starter", None, 42)
    truth = key["true_value_primary"]
    lin = next(m for m in key["methods"] if m["method"].startswith("Linear adjustment"))
    assert abs(lin["estimate"] - truth) / truth < 0.10
    naive = key["methods"][0]
    assert naive["verdict"] == "misses"
    post = next(m for m in key["methods"] if "points_redeemed" in m["method"])
    assert post["estimate"] < 0 < truth


def test_zero_effect_and_blind(tmp_path):
    out = tmp_path / "d"
    r = subprocess.run([sys.executable, str(G / "scripts" / "cg.py"), "generate", "retail-loyalty", "--level", "starter",
                        "--dials", '{"zero_effect": true}', "--out", str(out), "--blind"], capture_output=True, text=True, check=True)
    s = json.loads(r.stdout)
    assert "true_value" not in s and "quick_methods" not in s
    key = json.loads((tmp_path / "d-key" / "answer_key.json").read_text())
    assert abs(key["true_value_primary"]) < 1e-9
    assert (out / "data.csv").exists() and not (out / "answer_key.json").exists()
    # the exported script regenerates the same file
    subprocess.run([sys.executable, str(tmp_path / "d-key" / "generate.py"), "--out", str(tmp_path / "re")], check=True, capture_output=True)
    assert (tmp_path / "re" / "data.csv").read_bytes() == (out / "data.csv").read_bytes()


def _cg(*args, cwd):
    return subprocess.run([sys.executable, str(G / "scripts" / "cg.py"), *args], cwd=cwd, capture_output=True, text=True)


def test_blind_list_hides_teasers(tmp_path):
    full = _cg("list", cwd=tmp_path).stdout
    blind = _cg("list", "--blind", cwd=tmp_path).stdout
    teaser = json.loads((G / "scenarios" / "retail-loyalty.json").read_text())["teaser"]
    assert teaser in full and teaser not in blind


def test_key_dir_and_exact_regeneration(tmp_path):
    scn = json.loads((G / "scenarios" / "retail-loyalty.json").read_text())
    scn["ask"] = scn.get("ask", "") + " a ''' quote and a \\ backslash"   # must not break the exported script
    (tmp_path / "s.json").write_text(json.dumps(scn))
    r = _cg("generate", "s.json", "--level", "starter", "--n", "800", "--out", "share/d", "--key-dir", "sealed/d", "--blind", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert "true_value" not in out and "quick_methods" not in out
    assert not list((tmp_path / "share").rglob("answer_key.json"))
    assert (tmp_path / "sealed" / "d" / "answer_key.json").exists()
    rg = subprocess.run([sys.executable, "generate.py", "--out", str(tmp_path / "regen")], cwd=tmp_path / "sealed" / "d", capture_output=True, text=True)
    assert rg.returncode == 0, rg.stderr
    assert (tmp_path / "regen" / "data.csv").read_bytes() == (tmp_path / "share" / "d" / "data.csv").read_bytes()
    bad = _cg("generate", "s.json", "--level", "starter", "--n", "800", "--out", "share/e", "--key-dir", "share/e/key", cwd=tmp_path)
    assert bad.returncode != 0 and "inside the data folder" in bad.stderr


def test_set_blind_hides_truth(tmp_path):
    r = _cg("set", "retail-loyalty", "--level", "starter", "--n", "800", "--seeds", "2", "--out", "b/a", "--blind", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert "true_value" not in r.stdout and "plain_comparison" not in r.stdout
    assert (tmp_path / "b" / "a-key" / "set_summary.json").exists()


def test_key_uses_released_data():
    """With gaps in the drivers, the doubly robust quick estimate is no longer promised to 'work'."""
    scn = json.loads((G / "scenarios" / "retail-loyalty.json").read_text())
    _, _, key = E.generate(scn, "starter", {"missing": 0.2}, 3, 3000)
    dr = next(m for m in key["methods"] if m["method"].startswith("Flexible adjustment"))
    assert dr["expected"] != "should work" and "gaps" in dr["note"]
