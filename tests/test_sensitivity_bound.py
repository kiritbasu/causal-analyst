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
    # Cinelli & Hazlett (2020), table 2, checked against sensemakr 0.0.8 on the Darfur data: se
    # 0.02325654 with 783 degrees of freedom; `female` has partial R2 0.009081 with the treatment
    # and 0.1090 with the outcome. A hidden driver as strong as female gives a bias of 0.0220955.
    bias = core.ovb_bias_bound(0.02325654, 783, 0.009081, 0.1090, k=1.0)
    assert bias == pytest.approx(0.0220955, rel=1e-3)


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



def test_a_saturated_bound_is_flagged_capped():
    # Darfur's `village` (partial R2 0.417 with the treatment, 0.424 with the outcome) implies a
    # partial R2 above 1 with the outcome; the bias is then the cap's ceiling, not a real bound.
    one = core.ovb_bound(0.02325654, 783, 0.417, 0.424)
    assert one is not None and one["capped"] is True
    assert core.ovb_bound(0.02325654, 783, 0.009081, 0.1090)["capped"] is False
    assert core.ovb_bias_bound(0.02325654, 783, 0.417, 0.424) == one["bias"]


def test_rounding_below_zero_counts_as_zero():
    assert core.ovb_bias_bound(0.1, 1000, -1e-17, 0.1) == 0.0
    assert core.ovb_bias_bound(0.1, 1000, -1e-6, 0.1) is None


def test_every_benchmark_reports_its_own_bound():
    rng = np.random.default_rng(4)
    n = 2000
    x1, x2 = rng.normal(size=n), rng.normal(size=n)
    t = (rng.random(n) < 1 / (1 + np.exp(-(x1 + 0.3 * x2)))).astype(int)
    y = 1.5 * t + 2 * x1 + 0.5 * x2 + rng.normal(size=n)
    out = core.ols_sensitivity(pd.DataFrame({"t": t, "y": y, "x1": x1, "x2": x2}), "t", "y", ["x1", "x2"])
    for b in out["benchmarks"]:
        assert b["bias_k1"] == core.ovb_bias_bound(out["linear_se"], out["dof"], b["partial_r2_treatment"], b["partial_r2_outcome"])
        one = core.ovb_bound(out["linear_se"], out["dof"], b["partial_r2_treatment"], b["partial_r2_outcome"])
        assert b["bias_k1_capped"] is one["capped"]
    strongest = next(b for b in out["benchmarks"] if b["confounder"] == out["bias_bound"]["benchmark"])
    assert out["bias_bound"]["capped"] is strongest["bias_k1_capped"]
