"""Edge cases: bad plans fail clearly, odd codings work, grades follow the evidence, the report is safe."""
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "causal-analyst" / "scripts"
CA = SCRIPTS / "ca.py"
sys.path.insert(0, str(SCRIPTS))


def _data(n=500, seed=1, effect=2.0):
    rng = np.random.default_rng(seed)
    x = rng.normal(size=n)
    t = (rng.random(n) < 1 / (1 + np.exp(-x))).astype(int)
    y = effect * t + x + rng.normal(size=n)
    return x, t, y


def _run(tmp_path, df, **spec_kw):
    df.to_csv(tmp_path / "d.csv", index=False)
    spec = dict(data="d.csv", treatment="t", outcome="y", confounders=["x"], budget="quick", causalpfn_max_rows=0, seed=1)
    spec.update(spec_kw)
    (tmp_path / "spec.json").write_text(json.dumps(spec))
    p = subprocess.run([sys.executable, str(CA), "run", "spec.json", "--out", "r.json"], cwd=tmp_path, capture_output=True, text=True)
    res = json.loads((tmp_path / "r.json").read_text()) if (tmp_path / "r.json").exists() else None
    return p, res


# --- plans that must be refused with a clear message (exit code 2) -------------------------------

@pytest.mark.parametrize("case", ["three_values", "all_treated", "tiny", "missing_column", "bad_budget"])
def test_bad_plans_fail_clearly(tmp_path, case):
    x, t, y = _data()
    df = pd.DataFrame({"x": x, "t": t, "y": y})
    kw = {}
    if case == "three_values":
        df.loc[:99, "t"] = 2
    elif case == "all_treated":
        df["t"] = 1
    elif case == "tiny":
        df = df.head(12)
    elif case == "missing_column":
        kw = {"confounders": ["x", "nope"]}
    elif case == "bad_budget":
        kw = {"budget": "fast"}
    p, res = _run(tmp_path, df, **kw)
    assert p.returncode == 2, p.stderr[-500:]
    msg = json.loads(p.stdout[p.stdout.index("{"):])
    assert msg["error"] and "Traceback" not in p.stderr
    assert res is None


# --- odd but valid codings give the same answer ---------------------------------------------------

@pytest.mark.parametrize("coding", ["one_two", "yes_no", "bool"])
def test_codings_equivalent(tmp_path, coding):
    x, t, y = _data()
    tt = {"one_two": t + 1, "yes_no": np.where(t == 1, "yes", "no"), "bool": t.astype(bool)}[coding]
    p, res = _run(tmp_path, pd.DataFrame({"x": x, "t": tt, "y": y}))
    assert p.returncode == 0, p.stderr[-800:]
    lo, hi = res["main_result"]["ci"]
    assert lo < 2.0 < hi
    assert res["main_result"]["estimate"] > 0, "the higher / 'yes' value must be the action"


def test_zero_effect_not_downgraded(tmp_path):
    """No effect, clean randomized-like data: the grade should not drop just because the range covers zero."""
    rng = np.random.default_rng(5)
    n = 3000
    x = rng.normal(size=n)
    t = (rng.random(n) < 0.5).astype(int)
    y = x + rng.normal(size=n)
    p, res = _run(tmp_path, pd.DataFrame({"x": x, "t": t, "y": y}))
    assert p.returncode == 0, p.stderr[-800:]
    lo, hi = res["main_result"]["ci"]
    assert lo < 0 < hi
    assert res["trust_tier"] in ("A", "B"), res["trust_reasons"]


@pytest.mark.slow
def test_front_door(tmp_path):
    rng = np.random.default_rng(3)
    n = 3000
    x, u = rng.normal(size=n), rng.normal(size=n)
    t = (rng.random(n) < 1 / (1 + np.exp(-(0.5 * x + 1.2 * u)))).astype(int)
    m = t + 0.3 * x + rng.normal(size=n)
    y = 2.0 * m + x + 2.0 * u + rng.normal(size=n)  # true effect 2.0; u is hidden
    cb = {c: {"meaning": c, "confirmed": True} for c in "xtmy"}
    p, res = _run(tmp_path, pd.DataFrame({"x": x, "t": t, "m": m, "y": y}), mediators=["m"],
                  hidden_confounding="named_driver", hidden_driver_note="motivation", codebook=cb)
    assert p.returncode == 0, p.stderr[-800:]
    assert res["main_method"] == "front_door"
    lo, hi = res["main_result"]["ci"]
    assert lo < 2.0 < hi
    assert res["trust_tier"] == "C"
    assert res["estimates"]["aipw_gbm"]["estimate"] > 3, "adjustment alone is biased by the hidden driver"


# --- units ------------------------------------------------------------------------------------------

def test_att_se_covers():
    """The ATT standard error should give roughly 95% coverage (the -t*theta/p term matters)."""
    import ca_core as core
    hits = 0
    reps = 200
    for s in range(reps):
        rng = np.random.default_rng(100 + s)
        n = 800
        x = rng.normal(size=n)
        e = 1 / (1 + np.exp(-x))
        t = (rng.random(n) < e).astype(int)
        tau = 1 + x  # effect varies, so ATT differs from ATE
        y = x + tau * t + rng.normal(size=n)
        att_true = (1 + x[t == 1]).mean()
        r = core.aipw(y, t, e, x, x + tau, estimand="ATT")
        hits += r["ci"][0] <= att_true <= r["ci"][1]
    assert 0.88 <= hits / reps <= 0.99, hits / reps


def test_json_has_no_nan(tmp_path):
    import ca
    ca.dump({"a": float("nan"), "b": [1.0, float("inf")], "c": np.float64("nan")}, tmp_path / "x.json")
    assert json.loads((tmp_path / "x.json").read_text()) == {"a": None, "b": [1.0, None], "c": None}


def test_report_html_is_escaped():
    import ca_report
    s = ca_report._safe_html('<strong>+9</strong> <script>alert(1)</script><img src=x onerror=alert(1)>')
    assert "<strong>+9</strong>" in s
    assert "<script" not in s and "<img" not in s
    assert "Content-Security-Policy" in ca_report.CSP_META and "default-src 'none'" in ca_report.CSP_META


def test_dose_with_category_confounder(tmp_path):
    rng = np.random.default_rng(2)
    n = 800
    c = rng.choice(["north", "south", "west"], n)
    dose = rng.uniform(0, 10, n) + (c == "north") * 2
    y = 0.5 * dose + (c == "north") * 3 + rng.normal(size=n)
    p, res = _run(tmp_path, pd.DataFrame({"c": c, "t": dose, "y": y, "x": rng.normal(size=n)}),
                  treatment_type="continuous", contrast={"x0": 2, "x1": 6}, confounders=["x", "c"])
    assert p.returncode == 0, p.stderr[-800:]
    assert abs(res["main_result"]["estimate"] - 2.0) < 0.6
    assert math.isfinite(res["main_result"]["ci"][0])
