"""AIPW baseline: the target units' mean outcome without the action ("from X to Y")."""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "causal-analyst" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import ca_core as core  # noqa: E402


def _sim(n=4000, seed=7):
    """Confounded data with a known outcome model: Y(0) = 10 + 2x + noise, Y(1) = Y(0) + 1 + x."""
    rng = np.random.default_rng(seed)
    x = rng.normal(size=n)
    e = 1 / (1 + np.exp(-x))
    t = (rng.random(n) < e).astype(int)
    y0 = 10 + 2 * x + rng.normal(size=n)
    y1 = y0 + 1 + x
    y = np.where(t == 1, y1, y0)
    mu0, mu1 = 10 + 2 * x, 11 + 3 * x
    return x, t, y, e, mu0, mu1


def _aipw_before(y, t, e, mu0, mu1, estimand="ATE", eps=0.01):
    """ca_core.aipw as it was before the baseline was added, verbatim, for the no-change test."""
    e = core._clip(e, eps)
    n = len(y)
    if estimand == "ATT":
        p = t.mean()
        psi = (t * (y - mu0) - (1 - t) * e / (1 - e) * (y - mu0)) / p
        est = psi.mean()
        phi = psi - t * est / p
        se = phi.std(ddof=1) / math.sqrt(n)
    else:
        psi = mu1 - mu0 + t * (y - mu1) / e - (1 - t) * (y - mu0) / (1 - e)
        est = psi.mean()
        se = psi.std(ddof=1) / math.sqrt(n)
    ci = [float(est - 1.96 * se), float(est + 1.96 * se)]
    return {"estimate": float(est), "se": float(se), "ci": ci, "pseudo_outcomes": psi}


def test_ate_baseline_recovers_known_mean_without_action():
    _x, t, y, e, mu0, mu1 = _sim()
    # noisy nuisances, so the correction term does real work
    rng = np.random.default_rng(3)
    m0 = mu0 + 0.5 + 0.3 * rng.normal(size=len(y))
    m1 = mu1 - 0.4 + 0.3 * rng.normal(size=len(y))
    r = core.aipw(y, t, e, m0, m1, "ATE")
    ec = core._clip(e)
    phi0 = m0 + (1 - t) * (y - m0) / (1 - ec)
    se0 = phi0.std(ddof=1) / math.sqrt(len(y))
    truth = 10.0  # E[10 + 2x] with x ~ N(0, 1)
    assert abs(r["baseline"] - truth) < 3 * se0, (r["baseline"], se0)


def test_att_baseline_recovers_known_mean_without_action():
    x, t, y, e, mu0, mu1 = _sim()
    rng = np.random.default_rng(4)
    m0 = mu0 + 0.5 + 0.3 * rng.normal(size=len(y))
    r = core.aipw(y, t, e, m0, mu1, "ATT")
    truth = float((10 + 2 * x)[t == 1].mean())  # E[Y(0) | T=1] given the treated units' x
    ec = core._clip(e)
    p = t.mean()
    phi0 = (t * m0 + (1 - t) * ec / (1 - ec) * (y - m0)) / p - t * r["baseline"] / p
    se0 = phi0.std(ddof=1) / math.sqrt(len(y))
    assert abs(r["baseline"] - truth) < 3 * se0, (r["baseline"], truth, se0)


def test_ate_baseline_plus_effect_is_treated_potential_outcome_mean():
    _x, t, y, e, mu0, mu1 = _sim(seed=11)
    rng = np.random.default_rng(5)
    m0, m1 = mu0 + rng.normal(size=len(y)), mu1 + rng.normal(size=len(y))
    e_raw = np.clip(e + 0.2 * rng.normal(size=len(y)), 0, 1)  # some values hit the clip
    r = core.aipw(y, t, e_raw, m0, m1, "ATE")
    ec = core._clip(e_raw)
    ey1 = float((m1 + t * (y - m1) / ec).mean())
    assert r["baseline"] + r["estimate"] == pytest.approx(ey1, rel=1e-12, abs=1e-12)


def test_att_baseline_plus_effect_is_treated_observed_mean():
    _x, t, y, e, mu0, mu1 = _sim(seed=12)
    rng = np.random.default_rng(6)
    m0 = mu0 + rng.normal(size=len(y))
    r = core.aipw(y, t, e, m0, mu1, "ATT")
    treated_mean = float(y[t == 1].mean())
    assert r["baseline"] + r["estimate"] == pytest.approx(treated_mean, rel=1e-12, abs=1e-12)


@pytest.mark.parametrize("estimand", ["ATE", "ATT"])
def test_existing_outputs_unchanged(estimand):
    _x, t, y, e, mu0, mu1 = _sim(seed=13)
    rng = np.random.default_rng(8)
    m0, m1 = mu0 + rng.normal(size=len(y)), mu1 + rng.normal(size=len(y))
    new, old = core.aipw(y, t, e, m0, m1, estimand), _aipw_before(y, t, e, m0, m1, estimand)
    assert set(new) == set(old) | {"baseline"}
    for k in ("estimate", "se", "ci"):
        assert new[k] == old[k]  # exact: same floats, bit for bit
    assert np.array_equal(new["pseudo_outcomes"], old["pseudo_outcomes"])


@pytest.mark.slow
def test_pipeline_reports_baseline_on_aipw_entry():
    import ca
    rng = np.random.default_rng(21)
    n = 600
    x = rng.normal(size=n)
    t = (rng.random(n) < 1 / (1 + np.exp(-x))).astype(int)
    y = 5 + 2.0 * t + x + rng.normal(size=n)
    df = pd.DataFrame({"t": t, "y": y, "x": x})
    spec = dict(treatment="t", outcome="y", confounders=["x"], budget="quick",
                causalpfn_max_rows=0, seed=1)
    out = ca.analyse(df, spec)
    a = out["estimates"]["aipw_gbm"]
    assert isinstance(a["baseline"], float)
    # headline unchanged: still the median over seeds
    assert a["estimate"] == float(np.median(a["per_seed"]))
    assert "_k" not in a
    assert out["main_method"] == "aipw_gbm" and out["main_result"]["baseline"] == a["baseline"]
    assert abs(a["baseline"] - 5.0) < 0.5
    assert isinstance(out["estimates"]["aipw_spline"]["baseline"], float)


@pytest.mark.slow
def test_standard_budget_baseline_and_headline_come_from_one_fit():
    """With 3 seeds, main_result.baseline + estimate must equal the median-seed fit's E[Y(1)]."""
    import ca
    rng = np.random.default_rng(22)
    n = 600
    x = rng.normal(size=n)
    t = (rng.random(n) < 1 / (1 + np.exp(-x))).astype(int)
    y = 5 + 2.0 * t + x + rng.normal(size=n)
    df = pd.DataFrame({"t": t, "y": y, "x": x})
    spec = dict(treatment="t", outcome="y", confounders=["x"], budget="standard",
                causalpfn_max_rows=0, seed=1)
    out = ca.analyse(df, spec)
    mr = out["main_result"]
    assert out["main_method"] == "aipw_gbm" and len(mr["per_seed"]) == 3
    # rebuild the median-seed fit exactly as the pipeline does
    k = int(np.argsort(mr["per_seed"])[1])
    X = core.design_matrix(df, ["x"])
    e, m0, m1 = core.crossfit_nuisances(X, t, y.astype(float), "gbm", 5, 1 + k)
    fit = core.aipw(y.astype(float), t, e, m0, m1, "ATE")
    assert fit["estimate"] == mr["estimate"]
    assert mr["baseline"] == fit["baseline"]
    assert mr["baseline"] + mr["estimate"] == pytest.approx(fit["estimate"] + fit["baseline"], abs=1e-12)
