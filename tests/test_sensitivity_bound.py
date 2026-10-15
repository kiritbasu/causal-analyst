"""The Cinelli & Hazlett (2020) bias bound added to ols_sensitivity."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "causal-analyst" / "scripts"))
import ca_core as core  # noqa: E402


def test_matches_the_darfur_example():
    # Cinelli & Hazlett (2020), table 2 and sensemakr: the treatment estimate 0.0973 (se 0.0232,
    # 783 degrees of freedom); a hidden driver as strong as `female` (partial R2 0.0092 with the
    # treatment, 0.109 with the outcome) moves it to 0.0752, a bias of about 0.0221.
    bias = core.ovb_bias_bound(0.0232, 783, 0.00916, 0.109, k=1.0)
    assert bias == pytest.approx(0.0221, rel=0.03)


def test_grows_with_k_and_has_no_finite_bound_past_the_limit():
    small = core.ovb_bias_bound(0.1, 1000, 0.05, 0.1, k=0.5)
    one = core.ovb_bias_bound(0.1, 1000, 0.05, 0.1, k=1.0)
    two = core.ovb_bias_bound(0.1, 1000, 0.05, 0.1, k=2.0)
    assert 0 < small < one < two
    assert core.ovb_bias_bound(0.1, 1000, 0.6, 0.1, k=2.0) is None  # k * R2 >= 1
    assert core.ovb_bias_bound(0.1, 1000, 1.0, 0.1) is None
    assert core.ovb_bias_bound(0.1, 0, 0.05, 0.1) is None
    assert core.ovb_bias_bound(0.1, 1000, 0.0, 0.1) == 0.0  # no link to the treatment, no bias


def test_ols_sensitivity_reports_the_bound_and_keeps_its_other_fields():
    rng = np.random.default_rng(3)
    n = 2000
    x1, x2 = rng.normal(size=n), rng.normal(size=n)
    t = (rng.random(n) < 1 / (1 + np.exp(-(x1 + 0.3 * x2)))).astype(int)
    y = 1.5 * t + 2 * x1 + 0.5 * x2 + rng.normal(size=n)
    df = pd.DataFrame({"t": t, "y": y, "x1": x1, "x2": x2})
    out = core.ols_sensitivity(df, "t", "y", ["x1", "x2"])
    assert set(out) >= {"linear_estimate", "robustness_value", "robustness_value_significance",
                        "benchmarks", "strongest_measured", "linear_se", "dof", "bias_bound"}
    b = out["bias_bound"]
    assert b["k"] == 1.0 and b["benchmark"] == out["strongest_measured"]["confounder"] == "x1"
    s = out["strongest_measured"]
    expected = core.ovb_bias_bound(out["linear_se"], out["dof"], s["partial_r2_treatment"], s["partial_r2_outcome"])
    assert b["bias"] == expected > 0
