"""End-to-end smoke test: profile -> dag -> identify -> run -> report on the loyalty example."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CA = ROOT / "skills" / "causal-analyst" / "scripts" / "ca.py"
EX = ROOT / "examples" / "loyalty-program"


def ca(*args, cwd):
    subprocess.run([sys.executable, str(CA), *args], cwd=cwd, check=True, capture_output=True, text=True)


def test_pipeline(tmp_path):
    spec = json.loads((EX / "spec.json").read_text())
    spec.update(data=str(EX / "data.csv"), budget="quick", causalpfn_max_rows=0)
    spec.pop("allow_external_services", None)
    (tmp_path / "spec.json").write_text(json.dumps(spec))
    ca("profile", "--data", str(EX / "data.csv"), "--treatment", "joined_loyalty", "--outcome", "monthly_spend", "--out", "profile.json", cwd=tmp_path)
    ca("dag", "spec.json", "--outdir", ".", cwd=tmp_path)
    ca("identify", "spec.json", "--out", "identification.json", cwd=tmp_path)
    ca("run", "spec.json", "--out", "results.json", cwd=tmp_path)
    r = json.loads((tmp_path / "results.json").read_text())
    assert r["main_method"] == "aipw_gbm"
    lo, hi = r["main_result"]["ci"]
    assert lo < 9.17 < hi, "true effect (9.17) should be inside the 95% range"
    assert r["trust_tier"] in ("B", "C")
    bc = r["diagnostics"]["bad_control_illustration"]
    assert bc["also_controlling_for_excluded"]["estimate"] < 0 < bc["correct_controls"]["estimate"]
    ca("report", "results.json", "--narrative", str(EX / "narrative.json"), "--out", "report.html", cwd=tmp_path)
    html = (tmp_path / "report.html").read_text()
    assert "Why the grade is" in html and "Meet the methods" in html and "The data" in html
    assert r["data_overview"]["rows"] == 4000
    d = r["diagnostics"]
    assert d["alternatives"]["user"] and d["alternatives"]["leave_one_out"]
    assert "findings" in d["structure_check"]
    sim = d["simulation_check"]
    assert abs(sim["bias"]) < 0.25 * abs(sim["planted"])
    assert "What if our diagram is wrong?" in html


def test_design_traps(tmp_path):
    """AI-training case: controlling for the mediator or the collider must move the answer away from the truth."""
    ex = ROOT / "examples" / "ai-training"
    spec = json.loads((ex / "spec.json").read_text())
    spec.update(data=str(ex / "data.csv"), budget="quick", causalpfn_max_rows=0)
    (tmp_path / "spec.json").write_text(json.dumps(spec))
    ca("run", "spec.json", "--out", "results.json", cwd=tmp_path)
    r = json.loads((tmp_path / "results.json").read_text())
    lo, hi = r["main_result"]["ci"]
    assert lo < 7.5 < hi
    alts = {a["name"]: a["estimate"] for a in r["diagnostics"]["alternatives"]["user"] if a.get("illustrative")}
    assert len(alts) == 3 and all(v < 6 for v in alts.values()), alts


def test_not_identifiable(tmp_path):
    ex = ROOT / "examples" / "sales-calls"
    spec = json.loads((ex / "spec.json").read_text())
    spec.update(data=str(ex / "data.csv"), budget="quick", causalpfn_max_rows=0)
    (tmp_path / "spec.json").write_text(json.dumps(spec))
    ca("run", "spec.json", "--out", "results.json", cwd=tmp_path)
    r = json.loads((tmp_path / "results.json").read_text())
    assert r["trust_tier"] == "D" and r["main_result"] is None
    b = r["diagnostics"]["bounds_no_instrument"]["mtr_mts"]
    assert b["lower"] == 0 and b["upper"] > 0.2
