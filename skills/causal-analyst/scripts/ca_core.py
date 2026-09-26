"""Core numerical routines for the causal-analyst skill.

Every number the skill reports should come from these functions (via ca.py),
never from the model's own arithmetic. Keep functions deterministic given a seed.
"""
from __future__ import annotations

import hashlib
import json
import math
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")

# ----------------------------------------------------------------------------
# Data loading and profiling
# ----------------------------------------------------------------------------

def load_data(path: str) -> pd.DataFrame:
    if path.endswith(".parquet"):
        return pd.read_parquet(path)
    if path.endswith((".xlsx", ".xls")):
        return pd.read_excel(path)
    return pd.read_csv(path)


def file_fingerprint(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "ds-" + h.hexdigest()[:8]


def _col_kind(s: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(s):
        return "binary"
    if pd.api.types.is_numeric_dtype(s):
        vals = s.dropna().unique()
        if len(vals) <= 2:
            return "binary"
        if len(vals) <= 12 and np.allclose(vals, np.round(vals)):
            return "count/ordinal"
        return "number"
    if s.nunique(dropna=True) <= 30:
        return "category"
    return "text/id"


def profile(df: pd.DataFrame, treatment: str | None = None, outcome: str | None = None) -> dict:
    cols = []
    n = len(df)
    for c in df.columns:
        s = df[c]
        kind = _col_kind(s)
        info = {
            "column": c,
            "kind": kind,
            "missing_pct": round(float(s.isna().mean() * 100), 2),
            "n_unique": int(s.nunique(dropna=True)),
            "first_values": [None if pd.isna(v) else (v.item() if hasattr(v, "item") else v) for v in s.head(5).tolist()],
        }
        if pd.api.types.is_numeric_dtype(s):
            info.update(min=float(np.nanmin(s)), max=float(np.nanmax(s)), mean=float(np.nanmean(s)))
        cols.append(info)
    flags = []
    for info in cols:
        c = info["column"]
        sc = df[c]
        integer_like = (not pd.api.types.is_numeric_dtype(sc)) or bool(np.all(np.mod(sc.dropna().values, 1) == 0))
        if info["n_unique"] == n and info["kind"] in ("number", "text/id") and integer_like:
            flags.append({"column": c, "flag": "looks like an ID (unique whole numbers or codes); never use as a control"})
        if info["n_unique"] <= 1:
            flags.append({"column": c, "flag": "constant column"})
        if info["missing_pct"] > 20:
            flags.append({"column": c, "flag": f"{info['missing_pct']}% missing"})
        lname = c.lower()
        if "age" in lname and info.get("min") is not None and info["min"] < 0:
            flags.append({"column": c, "flag": "negative ages: impossible values"})
    if treatment is not None and treatment in df:
        t = df[treatment]
        if _col_kind(t) == "binary":
            t1 = t == t.max()
            for c in df.columns:
                if c in (treatment, outcome) or not pd.api.types.is_numeric_dtype(df[c]):
                    continue
                x = df[c]
                # values only (or almost only) non-zero among the treated -> likely a consequence of treatment
                nz_t = float((x[t1] != 0).mean()) if t1.any() else 0.0
                nz_c = float((x[~t1] != 0).mean()) if (~t1).any() else 0.0
                if nz_t > 0.5 and nz_c < 0.6 * nz_t and x.nunique() > 2:
                    flags.append({"column": c, "flag": f"non-zero for {nz_t:.0%} of treated vs {nz_c:.0%} of untreated: may be caused by the treatment (post-treatment) -- confirm timing before using as a control"})
                # near-deterministic predictor of treatment
                try:
                    from sklearn.metrics import roc_auc_score
                    auc = roc_auc_score(t1.astype(int), x.fillna(x.median()))
                    auc = max(auc, 1 - auc)
                    if auc > 0.97:
                        flags.append({"column": c, "flag": f"almost perfectly predicts the treatment (AUC {auc:.2f}): post-treatment variable, instrument, or no overlap -- ask the SME"})
                except Exception:
                    pass
            flags.append({"column": treatment, "flag": f"treated share {float(t1.mean()):.1%}"})
    return {"rows": n, "columns": cols, "flags": flags}


# ----------------------------------------------------------------------------
# Design matrix helpers
# ----------------------------------------------------------------------------

def design_matrix(df: pd.DataFrame, cols: list[str]) -> np.ndarray:
    if not cols:
        return np.zeros((len(df), 1))
    X = pd.get_dummies(df[cols], drop_first=True, dummy_na=False).astype(float)
    X = X.fillna(X.median())
    return X.values


def _learner(kind: str, task: str, seed: int):
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
    from sklearn.linear_model import LogisticRegression, LinearRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import SplineTransformer, StandardScaler

    if kind == "gbm":
        if task == "clf":
            return HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_leaf_nodes=15, random_state=seed)
        return HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_leaf_nodes=15, random_state=seed)
    if kind == "spline":
        if task == "clf":
            return make_pipeline(SplineTransformer(n_knots=5, degree=3, knots="quantile"), StandardScaler(), LogisticRegression(max_iter=3000, C=1.0))
        from sklearn.linear_model import RidgeCV
        return make_pipeline(SplineTransformer(n_knots=6, degree=3, knots="quantile"), RidgeCV(alphas=np.logspace(-4, 2, 13)))
    if task == "clf":
        return make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))
    return LinearRegression()


# ----------------------------------------------------------------------------
# Binary treatment estimators
# ----------------------------------------------------------------------------

def naive_diff(y, t):
    y1, y0 = y[t == 1], y[t == 0]
    est = y1.mean() - y0.mean()
    se = math.sqrt(y1.var(ddof=1) / len(y1) + y0.var(ddof=1) / len(y0))
    return {"estimate": est, "ci": [est - 1.96 * se, est + 1.96 * se], "se": se}


def _clip(p, eps=0.01):
    return np.clip(p, eps, 1 - eps)


def crossfit_nuisances(X, t, y, learner="gbm", folds=5, seed=0):
    """Out-of-fold propensity e(x), outcome models mu0(x), mu1(x)."""
    from sklearn.model_selection import StratifiedKFold

    n = len(y)
    e = np.zeros(n)
    mu0 = np.zeros(n)
    mu1 = np.zeros(n)
    skf = StratifiedKFold(n_splits=folds, shuffle=True, random_state=seed)
    for tr, te in skf.split(X, t):
        m_e = _learner(learner, "clf", seed).fit(X[tr], t[tr])
        e[te] = m_e.predict_proba(X[te])[:, 1]
        tr0, tr1 = tr[t[tr] == 0], tr[t[tr] == 1]
        mu0[te] = _learner(learner, "reg", seed).fit(X[tr0], y[tr0]).predict(X[te])
        mu1[te] = _learner(learner, "reg", seed).fit(X[tr1], y[tr1]).predict(X[te])
    return e, mu0, mu1


def aipw(y, t, e, mu0, mu1, estimand="ATE", eps=0.01):
    e = _clip(e, eps)
    n = len(y)
    if estimand == "ATT":
        p = t.mean()
        psi = (t * (y - mu0) - (1 - t) * e / (1 - e) * (y - mu0)) / p
        est = psi.mean()
        se = psi.std(ddof=1) / math.sqrt(n)
    else:
        psi = mu1 - mu0 + t * (y - mu1) / e - (1 - t) * (y - mu0) / (1 - e)
        est = psi.mean()
        se = psi.std(ddof=1) / math.sqrt(n)
    return {"estimate": float(est), "se": float(se), "ci": [float(est - 1.96 * se), float(est + 1.96 * se)], "pseudo_outcomes": psi}


def ipw_hajek(y, t, e, estimand="ATE", eps=0.01):
    e = _clip(e, eps)
    if estimand == "ATT":
        w1 = t
        w0 = (1 - t) * e / (1 - e)
    else:
        w1 = t / e
        w0 = (1 - t) / (1 - e)
    return float((w1 * y).sum() / w1.sum() - (w0 * y).sum() / w0.sum())


def reg_adjust(y, t, X, estimand="ATE", learner="linear", seed=0):
    m0 = _learner(learner, "reg", seed).fit(X[t == 0], y[t == 0])
    m1 = _learner(learner, "reg", seed).fit(X[t == 1], y[t == 1])
    d = m1.predict(X) - m0.predict(X)
    return float(d[t == 1].mean() if estimand == "ATT" else d.mean())


def bootstrap(fn, n, B=200, seed=0):
    r = np.random.default_rng(seed)
    out = []
    for _ in range(B):
        idx = r.integers(0, n, n)
        try:
            out.append(fn(idx))
        except Exception:
            continue
    out = np.array(out)
    return {"se": float(out.std(ddof=1)), "ci": [float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))], "n_boot": int(len(out))}


def dml_linear(y, t, X, seed=0):
    from econml.dml import LinearDML
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

    est = LinearDML(model_y=HistGradientBoostingRegressor(max_iter=200, random_state=seed),
                    model_t=HistGradientBoostingClassifier(max_iter=200, random_state=seed),
                    discrete_treatment=True, cv=5, random_state=seed)
    est.fit(y, t, X=None, W=X)
    lo, hi = est.ate_interval(X=None, alpha=0.05)
    return {"estimate": float(est.ate(X=None)), "ci": [float(np.ravel(lo)[0]), float(np.ravel(hi)[0])]}


def causal_forest(y, t, X, seed=0):
    from econml.dml import CausalForestDML
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

    est = CausalForestDML(model_y=HistGradientBoostingRegressor(max_iter=200, random_state=seed),
                          model_t=HistGradientBoostingClassifier(max_iter=200, random_state=seed),
                          discrete_treatment=True, n_estimators=300, min_samples_leaf=20, cv=5, random_state=seed)
    est.fit(y, t, X=X)
    ps = est.effect_inference(X).population_summary(alpha=0.05)
    lo, hi = ps.conf_int_mean()
    cate = est.effect(X)
    return {"estimate": float(ps.mean_point), "ci": [float(np.ravel(lo)[0]), float(np.ravel(hi)[0])], "cate": cate}


# ----------------------------------------------------------------------------
# Continuous treatment: dose contrast via g-computation
# ----------------------------------------------------------------------------

def dose_contrast(df, treatment, outcome, confounders, x0, x1, learner="spline", seed=0):
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.linear_model import LinearRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import SplineTransformer, StandardScaler, PolynomialFeatures

    cols = [treatment] + list(confounders)
    X = df[cols].astype(float).values
    y = df[outcome].astype(float).values
    if learner.startswith("spline"):
        # additive cubic splines with knots at data quantiles; n_knots encoded as spline<k>
        k = int(learner[6:] or 8)
        from sklearn.linear_model import RidgeCV
        model = make_pipeline(SplineTransformer(n_knots=k, degree=3, knots="quantile"), RidgeCV(alphas=np.logspace(-4, 2, 13)))
    elif learner == "gbm":
        model = HistGradientBoostingRegressor(max_iter=400, learning_rate=0.05, random_state=seed)
    else:
        model = LinearRegression()
    model.fit(X, y)
    X0, X1 = X.copy(), X.copy()
    X0[:, 0] = x0
    X1[:, 0] = x1
    return float(model.predict(X1).mean() - model.predict(X0).mean()), model


def cv_score(df, treatment, outcome, confounders, learner, seed=0):
    from sklearn.model_selection import KFold

    cols = [treatment] + list(confounders)
    X = df[cols].astype(float).values
    y = df[outcome].astype(float).values
    kf = KFold(5, shuffle=True, random_state=seed)
    errs = []
    for tr, te in kf.split(X):
        _, m = dose_contrast(df.iloc[tr], treatment, outcome, confounders, 0, 0, learner, seed)
        errs.append(np.mean((m.predict(X[te]) - y[te]) ** 2))
    return float(np.mean(errs))


# ----------------------------------------------------------------------------
# Diagnostics
# ----------------------------------------------------------------------------

def smd(x, t, w=None):
    if w is None:
        w = np.ones_like(x, dtype=float)
    def wm(a, ww):
        return np.sum(a * ww) / np.sum(ww)
    def wv(a, ww):
        m = wm(a, ww)
        return np.sum(ww * (a - m) ** 2) / np.sum(ww)
    m1, m0 = wm(x[t == 1], w[t == 1]), wm(x[t == 0], w[t == 0])
    v1, v0 = np.var(x[t == 1]), np.var(x[t == 0])
    sd = math.sqrt((v1 + v0) / 2) or 1.0
    return float((m1 - m0) / sd)


def ols_sensitivity(df, treatment, outcome, confounders):
    """Cinelli & Hazlett (2020) robustness value from a linear adjustment model,
    benchmarked against the strongest measured confounder."""
    import statsmodels.api as sm

    X = pd.get_dummies(df[[treatment] + list(confounders)], drop_first=True).astype(float)
    X = sm.add_constant(X)
    y = df[outcome].astype(float)
    fit = sm.OLS(y, X).fit()
    tval = fit.tvalues[treatment]
    dof = fit.df_resid
    f = abs(tval) / math.sqrt(dof)
    rv = 0.5 * (math.sqrt(f ** 4 + 4 * f ** 2) - f ** 2)
    # robustness value to lose significance at 5%
    fcrit = abs(stats.t.ppf(0.975, dof - 1)) / math.sqrt(dof - 1)
    fq = max(f - fcrit, 0)
    rv_sig = 0.5 * (math.sqrt(fq ** 4 + 4 * fq ** 2) - fq ** 2)
    # benchmark: partial R2 of each confounder with treatment and outcome
    bench = []
    for c in confounders:
        cols = [k for k in X.columns if k == c or k.startswith(c + "_")]
        if not cols:
            continue
        others = [k for k in X.columns if k not in cols]
        r_full_y = fit.rsquared
        r_red_y = sm.OLS(y, X[others]).fit().rsquared
        pr2_y = (r_full_y - r_red_y) / (1 - r_red_y) if r_red_y < 1 else 0
        Xt = X.drop(columns=[treatment])
        tt = df[treatment].astype(float)
        r_full_t = sm.OLS(tt, Xt).fit().rsquared
        r_red_t = sm.OLS(tt, Xt[[k for k in Xt.columns if k not in cols]]).fit().rsquared
        pr2_t = (r_full_t - r_red_t) / (1 - r_red_t) if r_red_t < 1 else 0
        bench.append({"confounder": c, "partial_r2_outcome": float(pr2_y), "partial_r2_treatment": float(pr2_t), "strength": float(math.sqrt(max(pr2_y, 0) * max(pr2_t, 0)))})
    bench.sort(key=lambda b: -b["strength"])
    strongest = bench[0] if bench else None
    return {"linear_estimate": float(fit.params[treatment]), "robustness_value": float(rv), "robustness_value_significance": float(rv_sig), "benchmarks": bench, "strongest_measured": strongest}


def iv_2sls(df, treatment, outcome, instrument, controls=()):
    import statsmodels.api as sm

    Z = sm.add_constant(pd.get_dummies(df[[instrument] + list(controls)], drop_first=True).astype(float))
    t = df[treatment].astype(float)
    fs = sm.OLS(t, Z).fit()
    fstat = float(fs.tvalues[instrument] ** 2)
    that = fs.predict(Z)
    Xs = Z.drop(columns=[instrument]).copy()
    Xs[treatment] = that
    ss = sm.OLS(df[outcome].astype(float), Xs).fit()
    # correct SE using residuals from structural equation with actual treatment
    Xa = Xs.copy(); Xa[treatment] = t
    resid = df[outcome].astype(float) - Xa @ ss.params
    sigma2 = float((resid ** 2).sum() / (len(resid) - Xs.shape[1]))
    XtX_inv = np.linalg.inv(Xs.T.values @ Xs.values)
    se = math.sqrt(sigma2 * XtX_inv[list(Xs.columns).index(treatment), list(Xs.columns).index(treatment)])
    est = float(ss.params[treatment])
    return {"estimate": est, "ci": [est - 1.96 * se, est + 1.96 * se], "first_stage_F": fstat}


def iv_bounds_binary(df, treatment, outcome, instrument, bins=5):
    """Manski-style bounds with an instrument (intersection across instrument levels).
    Requires binary treatment and outcome in [0,1] (outcome rescaled if needed)."""
    y = df[outcome].astype(float)
    lo_y, hi_y = float(y.min()), float(y.max())
    ys = (y - lo_y) / (hi_y - lo_y) if hi_y > lo_y else y * 0
    z = df[instrument]
    if z.nunique() > bins:
        z = pd.qcut(z, bins, labels=False, duplicates="drop")
    t = df[treatment].astype(int)
    L1, U1, L0, U0 = [], [], [], []
    for lev in sorted(z.unique()):
        m = z == lev
        p1 = t[m].mean()
        e1 = ys[m & (t == 1)].mean() if (m & (t == 1)).any() else 0.0
        e0 = ys[m & (t == 0)].mean() if (m & (t == 0)).any() else 0.0
        L1.append(e1 * p1); U1.append(e1 * p1 + (1 - p1))
        L0.append(e0 * (1 - p1)); U0.append(e0 * (1 - p1) + p1)
    lower = max(L1) - min(U0)
    upper = min(U1) - max(L0)
    scale = hi_y - lo_y
    return {"lower": float(lower * scale), "upper": float(upper * scale), "note": "Bounds on the average effect for everyone using only the instrument assumptions (no monotonicity). If lower>upper the instrument assumptions are contradicted by the data or sampling noise."}


def versions() -> dict:
    import importlib
    out = {}
    for m in ["numpy", "pandas", "scipy", "sklearn", "statsmodels", "econml", "dowhy"]:
        try:
            out[m] = importlib.import_module(m).__version__
        except Exception:
            out[m] = "missing"
    return out


# ----------------------------------------------------------------------------
# Partial identification without an instrument, power, bad-control illustration
# ----------------------------------------------------------------------------

def bounds_no_instrument(y, t, y_min=None, y_max=None):
    """Bounds on the ATE of a binary treatment when hidden confounding cannot be ruled out.

    worst_case (Manski): only assumes the outcome lies in [y_min, y_max].
    mtr_mts (Manski & Pepper): adds (i) monotone treatment response - the treatment never
    lowers anyone's outcome - and (ii) monotone treatment selection - those who got the
    treatment would have done at least as well without it as those who did not (positive
    selection, e.g. reps pick warmer accounts). Under both, 0 <= ATE <= naive difference.
    """
    y = np.asarray(y, float); t = np.asarray(t).astype(int)
    lo_y = float(np.min(y)) if y_min is None else float(y_min)
    hi_y = float(np.max(y)) if y_max is None else float(y_max)
    p = t.mean(); m1 = y[t == 1].mean(); m0 = y[t == 0].mean()
    wc_lo = (m1 * p + lo_y * (1 - p)) - (m0 * (1 - p) + hi_y * p)
    wc_hi = (m1 * p + hi_y * (1 - p)) - (m0 * (1 - p) + lo_y * p)
    naive = m1 - m0
    return {
        "outcome_range_assumed": [lo_y, hi_y],
        "worst_case": {"lower": float(wc_lo), "upper": float(wc_hi), "assumes": "outcome within the stated range only"},
        "mtr_mts": {"lower": 0.0, "upper": float(naive), "consistent_with_data": bool(naive >= 0),
                    "assumes": "treatment never lowers the outcome AND treated units would have done at least as well untreated (positive selection)"},
        "naive_difference": float(naive),
    }


def power_two_groups(baseline, lift, sd=None, alpha=0.05, power=0.8, ratio=1.0):
    """Units per group for a randomized test to detect `lift`.

    Binary outcome: pass baseline rate (e.g. 0.14) and absolute lift (0.05); sd is ignored.
    Numeric outcome: pass sd of the outcome; baseline is ignored.
    """
    from scipy.stats import norm
    za, zb = norm.ppf(1 - alpha / 2), norm.ppf(power)
    if sd is None:
        p1, p2 = float(baseline), float(baseline) + float(lift)
        var = p1 * (1 - p1) + p2 * (1 - p2) / ratio
    else:
        var = float(sd) ** 2 * (1 + 1 / ratio)
    n1 = (za + zb) ** 2 * var / float(lift) ** 2
    return {"per_group_control": int(math.ceil(n1)), "per_group_treated": int(math.ceil(n1 * ratio)),
            "total": int(math.ceil(n1)) + int(math.ceil(n1 * ratio)), "alpha": alpha, "power": power, "lift": lift,
            "baseline": baseline, "sd": sd}


def bad_control_illustration(df, treatment, outcome, confounders, bad_cols):
    """Linear regression with and without columns excluded as post-treatment, to show the SME
    what would have happened had they been used as controls. Illustration only."""
    import statsmodels.api as sm
    out = {}
    for name, cols in (("correct_controls", list(confounders)), ("also_controlling_for_excluded", list(confounders) + list(bad_cols))):
        X = pd.get_dummies(df[[treatment] + cols], drop_first=True).astype(float)
        X = sm.add_constant(X.fillna(X.median()))
        m = sm.OLS(df[outcome].astype(float), X).fit(cov_type="HC1")
        ci = m.conf_int().loc[treatment].tolist()
        out[name] = {"estimate": float(m.params[treatment]), "ci": [float(ci[0]), float(ci[1])], "columns": cols}
    out["excluded_columns"] = list(bad_cols)
    out["note"] = "Illustration only: shows how the answer changes if post-treatment columns are wrongly used as controls."
    return out


# ----------------------------------------------------------------------------
# Optional foundation-model cross-checks (used only when installed / configured)
# ----------------------------------------------------------------------------

def _causalpfn_weights():
    """Local CausalPFN weights: $CAUSALPFN_WEIGHTS, else the Hugging Face id (downloads if the network allows)."""
    import os
    p = os.environ.get("CAUSALPFN_WEIGHTS")
    if p and os.path.isdir(p):
        p = os.path.join(p, "causalpfn_v0.pt")
    return p if p and os.path.exists(p) else "vdblm/causalpfn"


def causalpfn_available():
    try:
        import causalpfn  # noqa: F401
        return True, _causalpfn_weights()
    except Exception as e:
        return False, f"not installed ({str(e)[:80]})"


def causalpfn_ate(X, t, y, n_samples=1000):
    """CausalPFN (in-context causal foundation model). Cross-check only: its intervals come from
    the model's posterior and were too narrow in our tests (missed the truth 2 of 14 times)."""
    import os
    import torch
    from causalpfn import CATEEstimator
    torch.set_num_threads(max(1, (os.cpu_count() or 2)))  # the script pins BLAS to 1 thread; torch can use all cores
    c = CATEEstimator(device="cpu", model_path=_causalpfn_weights()).fit(X.astype(float), t.astype(float), y.astype(float))
    ci = c._estimate_ate_cate_CI(X.astype(float), n_samples=n_samples)  # public estimate_ate_CI has a KeyError bug in 0.1.4
    cate = c.estimate_cate(X.astype(float))
    lo, hi = float(np.ravel(ci["ate_lower_bound"])[0]), float(np.ravel(ci["ate_upper_bound"])[0])
    return {"estimate": float(cate.mean()), "ci": [lo, hi], "cate": cate,
            "note": "Causal foundation model; interval is the model's own and tends to be too narrow."}


def _tabpfn_token():
    import os
    tok = os.environ.get("TABPFN_TOKEN")
    if tok:
        return tok.strip()
    f = os.environ.get("TABPFN_TOKEN_FILE")
    if f and os.path.exists(f):
        return open(f).read().strip()
    return None


def tabpfn_available(allow_external):
    """Returns (ok, mode, reason). mode 'api' sends data to Prior Labs; only allowed if the spec opts in."""
    tok = _tabpfn_token()
    if not tok:
        return False, None, "no TABPFN_TOKEN / TABPFN_TOKEN_FILE"
    if not allow_external:
        return False, None, "hosted TabPFN sends data to Prior Labs; add \"tabpfn_api\" to spec.allow_external_services to enable"
    try:
        import tabpfn_client  # noqa: F401
        return True, "api", "ok"
    except Exception as e:
        return False, None, f"tabpfn-client not installed ({str(e)[:80]})"


def aipw_tabpfn(X, t, y, estimand="ATE", folds=5, seed=0, max_train=10000):
    """AIPW with TabPFN (hosted API) outcome and propensity models, cross-fitted."""
    import os
    from sklearn.model_selection import StratifiedKFold
    from tabpfn_client import TabPFNClassifier, TabPFNRegressor, set_access_token
    set_access_token(_tabpfn_token())
    n = len(y)
    e = np.zeros(n); mu0 = np.zeros(n); mu1 = np.zeros(n)
    rng = np.random.default_rng(seed)
    skf = StratifiedKFold(n_splits=folds, shuffle=True, random_state=seed)
    for tr, te in skf.split(X, t):
        if len(tr) > max_train:
            tr = rng.choice(tr, max_train, replace=False)
        e[te] = TabPFNClassifier().fit(X[tr], t[tr]).predict_proba(X[te])[:, 1]
        for arm, arr in ((0, mu0), (1, mu1)):
            idx = tr[t[tr] == arm]
            arr[te] = TabPFNRegressor().fit(X[idx], y[idx]).predict(X[te])
    r = aipw(y, t, e, mu0, mu1, estimand)
    r.pop("pseudo_outcomes", None)
    r["note"] = "Doubly robust with TabPFN models (hosted by Prior Labs; data was sent to their API)."
    return r


# ----------------------------------------------------------------------------
# Data overview for the report
# ----------------------------------------------------------------------------

def data_overview(df: pd.DataFrame, spec: dict, sample_rows: int = 5, max_cols: int = 30) -> dict:
    """Shape, per-column role/type/missingness/summary, and a few sample rows."""
    T, Y = spec.get("treatment"), spec.get("outcome")
    roles = {T: "action", Y: "outcome"}
    for c in spec.get("confounders", []):
        roles[c] = "control"
    for c in spec.get("instruments", []):
        roles[c] = "nudge"
    for c in spec.get("mediators", []):
        roles[c] = "middle step"
    for c, why in spec.get("excluded", {}).items():
        roles.setdefault(c, "left out")
    order = {"action": 0, "outcome": 1, "control": 2, "nudge": 3, "middle step": 4, "left out": 5, "not used": 6}
    cols = sorted(df.columns, key=lambda c: (order[roles.get(c, "not used")], list(df.columns).index(c)))[:max_cols]
    out_cols = []
    for c in cols:
        s = df[c]
        kind = _col_kind(s)
        info = {"column": c, "role": roles.get(c, "not used"), "kind": kind,
                "missing_pct": float(s.isna().mean() * 100), "n_unique": int(s.nunique(dropna=True))}
        if c in spec.get("excluded", {}):
            info["why_left_out"] = str(spec["excluded"][c])
        if pd.api.types.is_numeric_dtype(s) and kind != "binary" and info["n_unique"] > 12:
            v = s.dropna().astype(float)
            counts, edges = np.histogram(v, bins=16)
            info.update(summary="numeric", min=float(v.min()), median=float(v.median()), mean=float(v.mean()), max=float(v.max()),
                        histogram={"counts": counts.tolist(), "edges": [float(x) for x in edges]})
        else:
            vc = s.astype(str).where(s.notna(), "(missing)").value_counts()
            info.update(summary="categories", top=[{"value": str(k), "count": int(n)} for k, n in vc.head(4).items()],
                        other=int(vc.iloc[4:].sum()))
        out_cols.append(info)
    sample = []
    if sample_rows and sample_rows > 0:
        show = [c for c in cols if roles.get(c) not in (None, "not used")][:10]
        for _, row in df[show].head(int(sample_rows)).iterrows():
            sample.append({c: (None if pd.isna(row[c]) else (row[c].item() if hasattr(row[c], "item") else str(row[c]))) for c in show})
    t = df[T] if T in df else None
    return {"rows": int(len(df)), "columns": int(df.shape[1]), "columns_shown": len(cols),
            "treated_share": float((t == t.max()).mean()) if t is not None and t.nunique() == 2 else None,
            "complete_rows_pct": float(df.notna().all(axis=1).mean() * 100),
            "column_info": out_cols, "sample_rows": sample}
