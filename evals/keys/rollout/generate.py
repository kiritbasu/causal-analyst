#!/usr/bin/env python3
"""Regenerate this dataset exactly: python generate.py [--out DIR]
Scenario saas-pricing-rollout, level realistic, seed 14. Requires numpy, pandas, scipy, statsmodels.
Edit SCENARIO / LEVEL / DIALS / SEED below to make variants."""

from __future__ import annotations

import copy
import hashlib
import json
import math

import numpy as np
import pandas as pd

LEVELS = ["starter", "realistic", "tricky", "unanswerable"]

LEVEL_DIALS = {
    "starter": {"nonlinear": 0.0, "heavy_tails": False, "overlap": "good", "missing": 0.0,
                "measurement_error": 0.0, "irrelevant": 0, "misleading_names": False, "zero_effect": False, "missing_pattern": "random"},
    "realistic": {"nonlinear": 0.3, "heavy_tails": False, "overlap": "good", "missing": 0.03,
                  "measurement_error": 0.0, "irrelevant": 2, "misleading_names": False, "zero_effect": False, "missing_pattern": "random"},
    "tricky": {"nonlinear": 0.6, "heavy_tails": True, "overlap": "weak", "missing": 0.08,
               "measurement_error": 0.15, "irrelevant": 3, "misleading_names": True, "zero_effect": False, "missing_pattern": "random"},
    "unanswerable": {"nonlinear": 0.3, "heavy_tails": False, "overlap": "good", "missing": 0.03,
                     "measurement_error": 0.0, "irrelevant": 2, "misleading_names": False, "zero_effect": False, "missing_pattern": "random"},
}

GENERIC_EXTRA = [("newsletter_opens", "newsletter emails opened last quarter", "poisson", {"mean": 3}),
                 ("app_rating", "last app store rating given (1-5)", "category", {"levels": [1, 2, 3, 4, 5], "probs": [.05, .07, .18, .35, .35]}),
                 ("area_density", "population density of home area (people per km², rounded)", "lognormal", {"median": 900, "spread": 0.9}),
                 ("support_tickets", "support tickets opened last year", "poisson", {"mean": 1.2}),
                 ("device_ios", "1 = mostly uses iOS", "binary", {"p": 0.45}),
                 ("signup_weekday", "day of week the account was created (0 = Monday)", "category", {"levels": [0, 1, 2, 3, 4, 5, 6], "probs": [1 / 7] * 7})]

sig = lambda x: 1.0 / (1.0 + np.exp(-x))


# ---------------------------------------------------------------------------- helpers
def level_ok(item, level):
    return LEVELS.index(item.get("min_level", "starter")) <= LEVELS.index(level) and \
        (item.get("max_level") is None or LEVELS.index(level) <= LEVELS.index(item["max_level"]))


def resolve(scn: dict, level: str, dials: dict | None = None) -> dict:
    """Apply the level (which items are active) and the realism dials to a scenario."""
    if level not in scn.get("levels", LEVELS):
        raise ValueError(f"{scn['id']} offers levels {scn.get('levels', LEVELS)}; '{level}' isn't one of them")
    s = copy.deepcopy(scn)
    s["level"] = level
    for lv in LEVELS[:LEVELS.index(level) + 1]:  # cumulative per-level overrides, e.g. {"tricky": {"rollout": {"trend_selection": 1.5}}}
        _deep_merge(s, s.get("level_overrides", {}).get(lv, {}))
    d = dict(LEVEL_DIALS[level])
    d.update(s.get("level_dials", {}).get(level, {}))
    d.update(dials or {})
    s["dials"] = d
    for key in ("variables", "hidden", "post_treatment", "notes", "irrelevant", "traps"):
        s[key] = [x for x in s.get(key, []) if level_ok(x, level)]
    for v in s["variables"]:
        for k in ("to_treat", "to_outcome"):
            if v.get(k + "_from") and LEVELS.index(level) < LEVELS.index(v[k + "_from"]):
                v[k] = 0
    for key in ("instrument", "mediator", "negative_control", "heterogeneity"):
        if s.get(key) and not level_ok(s[key], level):
            s[key] = None
    if d.get("zero_effect"):
        s.setdefault("effect", {})["ate"] = 0.0
        if s.get("heterogeneity"):
            s["heterogeneity"] = None
    return s


def _deep_merge(a, b):
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            _deep_merge(a[k], v)
        else:
            a[k] = copy.deepcopy(v)
    return a


def _latent(n, rng):
    return rng.standard_normal(n)


def _transform(z, dist, rng):
    """Map a standardized latent to the column's distribution (monotone, so effects keep sign)."""
    t = dist.get("type", "normal")
    if t == "normal":
        return dist.get("mean", 0) + dist.get("sd", 1) * z
    if t == "lognormal":
        return dist.get("median", 1) * np.exp(dist.get("spread", 0.5) * z)
    if t == "binary":
        p = dist.get("p", 0.5)
        return (z > np.quantile(z, 1 - p)).astype(int)
    if t == "poisson":
        lam = dist.get("mean", 2) * np.exp(0.45 * z - 0.45 ** 2 / 2)
        return rng.poisson(lam)
    if t == "category":
        levels, probs = dist["levels"], np.array(dist.get("probs") or [1 / len(dist["levels"])] * len(dist["levels"]))
        cuts = np.quantile(z, np.cumsum(probs)[:-1] / probs.sum())
        return np.array(levels, dtype=object)[np.searchsorted(cuts, z)]
    if t == "uniform":
        from scipy.stats import norm
        return dist.get("low", 0) + (dist.get("high", 1) - dist.get("low", 0)) * norm.cdf(z)
    raise ValueError(f"unknown dist {t}")


def _finish(x, v):
    if "clip" in v:
        x = np.clip(x, *v["clip"])
    if v.get("decimals") is not None and np.issubdtype(np.asarray(x).dtype, np.number):
        x = np.round(x, v["decimals"])
        if v["decimals"] == 0:
            x = x.astype(int)
    return x


def _g(z, nl):
    """Standardized driver with optional curvature (keeps mean ~0)."""
    return z + nl * (z ** 2 - 1) / math.sqrt(2)


def _calibrate(fn, target, lo=-15.0, hi=15.0, it=60):
    for _ in range(it):
        mid = (lo + hi) / 2
        if fn(mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _noise(n, sd, heavy, rng):
    if heavy:
        return sd * rng.standard_t(3, n) / math.sqrt(3)
    return sd * rng.standard_normal(n)


def fingerprint(df: pd.DataFrame) -> str:
    return "gt-" + hashlib.sha256(pd.util.hash_pandas_object(df, index=False).values.tobytes()).hexdigest()[:6]


# ---------------------------------------------------------------------------- cross-section / cutoff
def _drivers(s, n, rng):
    """Hidden drivers, then recorded variables in order. Returns latent dict, values dict."""
    nl = s["dials"]["nonlinear"]
    U = {h["name"]: _latent(n, rng) for h in s["hidden"]}
    Z, X = {}, {}
    for v in s["variables"]:
        z = _latent(n, rng)
        for p, c in v.get("depends_on", {}).items():
            if p in Z:
                z = z + c * Z[p]
        for h, c in v.get("from_hidden", {}).items():
            if h in U:
                z = z + c * U[h]
        z = (z - z.mean()) / z.std()
        Z[v["name"]] = z
        X[v["name"]] = _finish(_transform(z, v.get("dist", {"type": "normal"}), rng), v)
    # Effects act on the recorded values (standardized), so a correct linear adjustment really is
    # correct at the 'starter' level; curvature comes only from the nonlinear dial.
    R = {}
    for v in s["variables"]:
        x = X[v["name"]]
        if v.get("dist", {}).get("type") == "category":
            lv = v["dist"]["levels"]
            x = np.array([lv.index(a) for a in x], dtype=float)
        x = np.asarray(x, dtype=float)
        R[v["name"]] = (x - x.mean()) / (x.std() + 1e-12)
    return U, R, X, nl


def _index(s, Z, U, key, nl, curved_first=2):
    """Linear (optionally curved) index of drivers for the treatment (key='to_treat') or outcome."""
    idx = 0.0
    k = 0
    for v in s["variables"]:
        c = v.get(key, 0)
        if c:
            g = _g(Z[v["name"]], nl) if k < curved_first else Z[v["name"]]
            idx = idx + c * g
            k += 1
    for h in s["hidden"]:
        c = h.get(key, 0)
        if c:
            idx = idx + c * U[h["name"]]
    return idx


def _treatment(s, n, rng, Z, U, X, nl):
    tr = s["treatment"]
    lin = _index(s, Z, U, "to_treat", nl)
    if s["dials"]["overlap"] == "weak":
        lin = lin * 2.2
    inst = s.get("instrument")
    zins = None
    if inst:
        zins = (rng.random(n) < inst.get("p", 0.5)).astype(int)
    uT = rng.random(n)
    out = {"lin": lin, "zins": zins, "uT": uT}
    if s["design"] == "cutoff":
        rv = s["cutoff"]["running"]
        thr = s["cutoff"]["threshold"]
        above = (X[rv] >= thr).astype(int)
        if s["cutoff"].get("fuzzy"):
            p_hi, p_lo = s["cutoff"].get("p_above", 0.85), s["cutoff"].get("p_below", 0.08)
            T = (uT < np.where(above == 1, p_hi, p_lo)).astype(int)
        else:
            T = above
        out.update(T=T, above=above)
        return out
    if tr.get("type", "binary") == "binary":
        share = tr.get("share", 0.4)
        zt = inst.get("strength", 1.0) if inst else 0.0
        c = _calibrate(lambda a: float(np.mean(sig(a + lin + zt * (zins if zins is not None else 0)))), share)
        p1 = sig(c + lin + zt) if inst else None
        p0 = sig(c + lin) if inst else None
        p = sig(c + lin + zt * zins) if inst else sig(c + lin)
        T = (uT < p).astype(int)
        out.update(T=T, ps=p)
        if inst:
            out.update(T_z1=(uT < p1).astype(int), T_z0=(uT < p0).astype(int))
        return out
    # amount / dose
    lo, hi = tr["min"], tr["max"]
    step = tr.get("step", 1)
    raw = (lin - lin.mean()) / (lin.std() + 1e-9) * tr.get("spread", 0.8) + rng.standard_normal(n) * tr.get("noise", 0.6)
    raw = (raw - raw.mean()) / raw.std()
    d = lo + (hi - lo) * (0.5 + tr.get("width", 0.26) * raw)
    d = np.clip(np.round(d / step) * step, lo, hi)
    out.update(T=d)
    return out


def _tau(s, X, n):
    """Individual effect of a yes/no action (continuous-outcome scale), mean = ate."""
    ate = float(s.get("effect", {}).get("ate", 0))
    het = s.get("heterogeneity")
    if not het:
        return np.full(n, ate), None
    seg = _segment(het, X)
    extra = float(het["extra"])
    base = ate - extra * seg.mean()
    return base + extra * seg, seg


def _segment(het, X):
    x = X[het["variable"]]
    if "below" in het:
        return (np.asarray(x, dtype=float) < het["below"]).astype(float)
    if "above" in het:
        return (np.asarray(x, dtype=float) >= het["above"]).astype(float)
    return (np.asarray(x) == het["equals"]).astype(float)


def _dose_effect(s, d):
    e = s["effect"]
    if e.get("shape", "linear") == "linear":
        return e["per_unit"] * d
    return e["max_effect"] * (1 - np.exp(-d / e["scale"]))  # curved: diminishing returns


def _outcome_cs(s, n, rng, Z, U, X, nl, trt):
    y = s["outcome"]
    kind = y.get("type", "continuous")
    heavy = s["dials"]["heavy_tails"]
    T = trt["T"]
    base_idx = _index(s, Z, U, "to_outcome", nl)
    if nl:
        vs = [v for v in s["variables"] if v.get("to_outcome")]
        if len(vs) >= 2:
            a, b = Z[vs[0]["name"]], Z[vs[1]["name"]]
            base_idx = base_idx + nl * 0.5 * (vs[0]["to_outcome"] + vs[1]["to_outcome"]) / 2 * (a * b)
    med = s.get("mediator")
    dose = s["treatment"].get("type") == "dose"
    res = {}
    if kind == "continuous":
        eps = _noise(n, y.get("noise_sd", 1.0), heavy, rng)
        base = y.get("base", 0) + base_idx + eps
        if dose:
            f = lambda d: base + _dose_effect(s, d)
            Y = f(T)
            grid = s["treatment"].get("grid") or list(np.linspace(s["treatment"]["min"], s["treatment"]["max"], 5))
            curve = {str(g): float(np.mean(_clipy(f(np.full(n, g)), y) - _clipy(f(np.full(n, grid[0])), y))) for g in grid}
            Ycl = _clipy(Y, y)
            res.update(Y=Ycl, dose_curve=curve, grid=grid)
            return res
        tau, seg = _tau(s, X, n)
        if med:
            m_eps = rng.standard_normal(n) * med.get("noise_sd", 1.0)
            m0 = med.get("base", 0) + m_eps + _mix(med.get("from_vars", {}), Z)
            a = med["from_treat"]
            M0, M1 = m0, m0 + a
            share = med.get("share", 0.5)
            bcoef = share * tau / a
            direct = (1 - share) * tau
            Y0 = base + bcoef * M0
            Y1 = base + direct + bcoef * M1
            M = np.where(T == 1, M1, M0)
            res.update(M=_finish(M, med))
        else:
            Y0, Y1 = base, base + tau
        Y0c, Y1c = _clipy(Y0, y), _clipy(Y1, y)
        res.update(Y=np.where(T == 1, Y1c, Y0c), Y0=Y0c, Y1=Y1c, seg=seg, tau_i=Y1c - Y0c)
        return res
    # binary / count outcomes: effect given on the probability / mean scale, calibrated
    uY = rng.random(n)
    target = float(s.get("effect", {}).get("ate", 0))
    rate = y.get("base_rate", 0.2)
    link = (lambda x: sig(x)) if kind == "binary" else (lambda x: np.exp(x))
    inv0 = math.log(rate / (1 - rate)) if kind == "binary" else math.log(rate)
    c = _calibrate(lambda a: float(np.mean(link(a + base_idx))), rate, inv0 - 10, inv0 + 10)
    het = s.get("heterogeneity")
    seg = _segment(het, X) if het else np.zeros(n)
    ratio = float(het["extra_ratio"]) if het else 1.0  # effect in the segment is this many times larger (log-odds)
    shift = lambda dlt: dlt * (1 + (ratio - 1) * seg)
    dl = _calibrate(lambda dlt: float(np.mean(link(c + base_idx + shift(dlt)) - link(c + base_idx))), target, -8, 8) if target else 0.0
    p0 = link(c + base_idx)
    p1 = link(c + base_idx + shift(dl))
    if kind == "binary":
        Y0, Y1 = (uY < p0).astype(int), (uY < p1).astype(int)
    else:
        from scipy.stats import poisson
        Y0, Y1 = poisson.ppf(uY, p0).astype(int), poisson.ppf(uY, p1).astype(int)
    res.update(Y=np.where(T == 1, Y1, Y0), Y0=Y0, Y1=Y1, seg=seg if het else None, tau_i=p1 - p0, p0=p0)
    return res


def _mix(coefs, Z):
    out = 0.0
    for k, c in coefs.items():
        if k in Z:
            out = out + c * Z[k]
    return out


def _clipy(v, y):
    lo, hi = y.get("min"), y.get("max")
    if lo is not None or hi is not None:
        v = np.clip(v, lo if lo is not None else -np.inf, hi if hi is not None else np.inf)
    return v


def _extras(s, n, rng, Z, U, X, trt, out):
    """Consequences / colliders, negative-control outcome, irrelevant columns."""
    T, Y = trt["T"], out["Y"]
    cols = {}
    ystd = (Y - np.mean(Y)) / (np.std(Y) + 1e-9)
    for p in s["post_treatment"]:
        base = p.get("base", 0) + p.get("from_treat", 0) * T + p.get("from_outcome", 0) * ystd + _mix(p.get("from_vars", {}), Z)
        v = base + rng.standard_normal(n) * p.get("noise_sd", 1.0)
        if p.get("treated_only"):
            leak = p.get("leak_share", 0.0)
            keep = (T == 1) | (rng.random(n) < leak)
            v = np.where(keep, v, 0)
        cols[p["name"]] = _finish(v, p)
    nc = s.get("negative_control")
    if nc:
        idx = _mix(nc.get("from_vars", {}), Z)
        for h, c in nc.get("from_hidden", {}).items():
            if h in U:
                idx = idx + c * U[h]
        if nc.get("type", "binary") == "binary":
            rate = nc.get("base_rate", 0.05)
            a = _calibrate(lambda a: float(np.mean(sig(a + idx))), rate)
            cols[nc["name"]] = (rng.random(n) < sig(a + idx)).astype(int)
        else:
            cols[nc["name"]] = _finish(nc.get("base", 0) + idx + rng.standard_normal(n) * nc.get("noise_sd", 1), nc)
    k = s["dials"]["irrelevant"]
    extras = list(s.get("irrelevant", [])) + [{"name": a, "meaning": b, "dist": {"type": t, **p}} for a, b, t, p in GENERIC_EXTRA]
    for e in extras[:k]:
        e = dict(e)
        e.setdefault("decimals", 0 if e["dist"]["type"] in ("lognormal", "poisson", "binary") else None)
        cols[e["name"]] = _finish(_transform(_latent(n, rng), e["dist"], rng), e)
        e.setdefault("recorded", "before the action")
        s.setdefault("_extra_cols", []).append(e)
    return cols


def _apply_realism(s, df, rng, protect):
    d = s["dials"]
    # measurement error on recorded drivers flagged noisy
    if d["measurement_error"]:
        for v in s["variables"]:
            if v.get("noisy") and v["name"] in df and pd.api.types.is_numeric_dtype(df[v["name"]]) and df[v["name"]].nunique() > 10:
                x = df[v["name"]].astype(float)
                df[v["name"]] = _finish(x + rng.standard_normal(len(x)) * x.std() * d["measurement_error"] * 3, v)
    if d["missing"]:
        cand = [c for c in df.columns if c not in protect]
        rate = np.full(len(df), float(d["missing"]))
        T = s["treatment"]["name"]
        if d.get("missing_pattern", "random") == "depends_on_action" and T in df and s["treatment"].get("type", "binary") == "binary":
            # gaps depend on the group: e.g. members' details are filled in at sign-up, others' aren't
            rate = np.where(df[T].values == 1, 0.4, 1.6) * d["missing"]
        for c in cand:
            m = rng.random(len(df)) < rate
            if df[c].dtype == object:
                df[c] = df[c].astype(object).where(~m, None)
            elif pd.api.types.is_integer_dtype(df[c]):
                df[c] = df[c].astype("Int64").mask(m)
            else:
                df[c] = df[c].where(~m)
    return df


def _names(s):
    """Raw column names (cryptic ones when misleading_names is on)."""
    m = s["dials"]["misleading_names"]
    ren = {}
    for grp in ("variables", "post_treatment"):
        for v in s.get(grp, []):
            if m and v.get("cryptic"):
                ren[v["name"]] = v["cryptic"]
    for key in ("treatment", "outcome", "mediator", "negative_control", "instrument"):
        v = s.get(key)
        if v and m and v.get("cryptic"):
            ren[v["name"]] = v["cryptic"]
    return ren


def _quick_ols(df, y, t, controls):
    import statsmodels.api as sm
    X = pd.get_dummies(df[[t] + controls], drop_first=True).astype("float64")
    X = sm.add_constant(X.fillna(X.median()))  # simple median fill for gaps
    m = sm.OLS(df[y].astype(float), X).fit(cov_type="HC1")
    lo, hi = m.conf_int().loc[t]
    return float(m.params[t]), [float(lo), float(hi)]


def _row(label, est, truth, expected, note="", ci=None):
    """A quick estimate against the truth. Verdicts account for sampling noise when a range is known."""
    if isinstance(est, tuple):
        est, ci = est
    off = (est - truth) / abs(truth) if truth else None
    # 'within noise' uses a 99% range (the stored range95 is the usual 95%) so honest sampling luck isn't flagged
    covers = bool(ci) and (ci[0] - 0.33 * (ci[1] - ci[0]) / 2) <= truth <= (ci[1] + 0.33 * (ci[1] - ci[0]) / 2)
    if truth == 0:
        verdict = "recovers truth" if covers or abs(est) < 1e-9 else "misses"
    elif abs(off) <= 0.03:
        verdict = "recovers truth"
    elif abs(off) <= 0.10 or covers:
        verdict = "close" if abs(off) <= 0.10 else "within noise"
    else:
        verdict = "misses"
    return {"method": label, "estimate": est, "range95": ci, "off_by_pct": None if off is None else round(100 * off, 1),
            "expected": expected, "verdict": verdict, "note": note}


def _boot(fn, df, B=150, seed=7, cluster=None):
    rng = np.random.default_rng(seed)
    est = fn(df)
    vals = []
    if cluster:
        ids = df[cluster].unique()
        groups = {k: g for k, g in df.groupby(cluster)}
        for _ in range(B):
            pick = rng.choice(ids, len(ids), replace=True)
            d = pd.concat([groups[k].assign(**{cluster: f"{k}_{i}"}) for i, k in enumerate(pick)], ignore_index=True)
            vals.append(fn(d))
    else:
        for _ in range(B):
            vals.append(fn(df.iloc[rng.integers(0, len(df), len(df))]))
    vals = np.array([v for v in vals if np.isfinite(v)])
    se = float(vals.std()) if len(vals) > 5 else float("nan")
    return float(est), [float(est - 1.96 * se), float(est + 1.96 * se)]


def _aipw(df, y, t, controls, seed=1):
    """Quick cross-fitted doubly robust estimate (gradient boosting), the 'should work' reference."""
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
    X = pd.get_dummies(df[controls], drop_first=True).astype("float64").to_numpy(dtype=float, na_value=np.nan)  # boosting handles gaps
    T = df[t].astype(int).values
    Y = df[y].astype(float).values
    n = len(Y)
    rng = np.random.default_rng(seed)
    fold = rng.integers(0, 2, n)
    e = np.zeros(n); m0 = np.zeros(n); m1 = np.zeros(n)
    for k in (0, 1):
        tr, te = fold != k, fold == k
        kw = dict(max_iter=200, learning_rate=0.05, max_leaf_nodes=15, random_state=seed)
        e[te] = HistGradientBoostingClassifier(**kw).fit(X[tr], T[tr]).predict_proba(X[te])[:, 1]
        m0[te] = HistGradientBoostingRegressor(**kw).fit(X[tr][T[tr] == 0], Y[tr][T[tr] == 0]).predict(X[te])
        m1[te] = HistGradientBoostingRegressor(**kw).fit(X[tr][T[tr] == 1], Y[tr][T[tr] == 1]).predict(X[te])
    e = np.clip(e, 0.02, 0.98)
    psi = m1 - m0 + T * (Y - m1) / e - (1 - T) * (Y - m0) / (1 - e)
    est, se = float(psi.mean()), float(psi.std() / math.sqrt(n))
    return est, [est - 1.96 * se, est + 1.96 * se]


def generate_cross_section(s, seed):
    rng = np.random.default_rng(seed)
    n = int(s["n"])
    U, Z, X, nl = _drivers(s, n, rng)
    trt = _treatment(s, n, rng, Z, U, X, nl)
    out = _outcome_cs(s, n, rng, Z, U, X, nl, trt)
    extra = _extras(s, n, rng, Z, U, X, trt, out)
    tr, y = s["treatment"], s["outcome"]
    data = {}
    if s.get("id_col"):
        data[s["id_col"]["name"]] = np.arange(s["id_col"].get("start", 100001), s["id_col"].get("start", 100001) + n)
    for v in s["variables"]:
        data[v["name"]] = X[v["name"]]
    if s.get("instrument"):
        data[s["instrument"]["name"]] = trt["zins"]
    data[tr["name"]] = trt["T"]
    if "M" in out:
        data[s["mediator"]["name"]] = out["M"]
    data.update(extra)
    data[y["name"]] = _finish(out["Y"], y)
    df = pd.DataFrame(data)
    protect = {tr["name"], y["name"]} | ({s["id_col"]["name"]} if s.get("id_col") else set())
    df = _apply_realism(s, df, rng, protect)
    # Quick estimates use the released data (noise and gaps included), so they show what an analyst can get.
    key = _key_cross_section(s, df, out, trt, X)
    ren = _names(s)
    df = df.rename(columns=ren)
    key["column_names"] = {k: v for k, v in ren.items()}
    return df, key


def _key_cross_section(s, df, out, trt, X):
    tr, y = s["treatment"], s["outcome"]
    T, Yn = tr["name"], y["name"]
    key = {"targets": [], "methods": []}
    dose = tr.get("type") == "dose"
    d = s["dials"]
    active = [h for h in s["hidden"] if h.get("to_treat") and h.get("to_outcome")]
    proxied = [h for h in active if any(h["name"] in v.get("from_hidden", {}) for v in s["variables"])]
    unproxied = [h for h in active if h not in proxied]
    confounded = bool(active) or any(v.get("to_treat") and v.get("to_outcome") for v in s["variables"])
    if dose:
        curve = out["dose_curve"]
        grid = out["grid"]
        key["targets"].append({"name": "dose_curve", "label": f"Average change in {Yn} compared with {T} = {grid[0]}", "values": curve, "primary": True})
        slope = (curve[str(grid[-1])] - curve[str(grid[0])]) / (grid[-1] - grid[0])
        key["targets"].append({"name": "average_slope", "label": f"Average effect per 1 unit of {T} across {grid[0]} to {grid[-1]}", "value": slope})
        truth = slope
    elif s["design"] == "cutoff":
        rv, thr = s["cutoff"]["running"], s["cutoff"]["threshold"]
        r = np.asarray(X[rv], dtype=float)
        h = s["cutoff"].get("truth_window", (r.max() - r.min()) * 0.02)
        near = np.abs(r - thr) <= h
        tau_i = out["tau_i"]
        truth = float(np.mean(tau_i[near]))
        key["targets"].append({"name": "effect_at_cutoff", "label": f"Effect for units right at the cutoff ({rv} = {thr})", "value": truth, "primary": True})
        key["targets"].append({"name": "ate", "label": "Average effect for everyone (this design can't recover it)", "value": float(np.mean(tau_i))})
        if s["cutoff"].get("fuzzy"):
            key["targets"][0]["note"] = "Fuzzy cutoff: only part of the eligible group takes it up; the estimate is for those whose take-up the cutoff changed, at the cutoff."
    else:
        tau_i = out["tau_i"]
        est = s.get("estimand", "ATE")
        key["targets"].append({"name": "ate", "label": "Average effect for everyone", "value": float(np.mean(tau_i)), "primary": est == "ATE"})
        key["targets"].append({"name": "att", "label": "Average effect for those who got the action", "value": float(np.mean(tau_i[trt["T"] == 1])), "primary": est == "ATT"})
        if out.get("seg") is not None:
            het = s["heterogeneity"]
            seg = out["seg"].astype(bool)
            key["targets"].append({"name": "segment_effects", "label": f"Effect by group ({het.get('label', het['variable'])})",
                                   "values": {het.get("label", "segment"): float(np.mean(tau_i[seg])), "everyone else": float(np.mean(tau_i[~seg]))}})
        if s.get("instrument"):
            comp = (trt["T_z1"] == 1) & (trt["T_z0"] == 0)
            key["targets"].append({"name": "late", "label": f"Effect for those whose action depended on {s['instrument']['name']} (compliers)",
                                   "value": float(np.mean(tau_i[comp])), "share_compliers": float(comp.mean())})
        truth = next(t["value"] for t in key["targets"] if t.get("primary"))
    rec = [v["name"] for v in s["variables"] if v.get("role") != "running" and (v.get("to_treat") or v.get("to_outcome") or v.get("role") == "proxy")]
    m = key["methods"]
    clean = not d["nonlinear"] and not d["measurement_error"]
    if dose:
        m.append(_row("Plain comparison (straight line, no adjustment)", _quick_ols(df, Yn, T, []), truth, "should fail" if confounded else "can mislead"))
        m.append(_row("Adjust for recorded drivers, straight-line dose", _quick_ols(df, Yn, T, rec), truth, "can mislead", "a straight line misstates a curved effect"))
        dcat = df.copy()
        dcat["_dose"] = dcat[T].astype(str)
        dcat[T + "_lvl"] = dcat[T]
        est_curve = _dose_curve_ols(dcat, Yn, T, rec, out["grid"])
        slope = (est_curve[-1] - est_curve[0]) / (out["grid"][-1] - out["grid"][0])
        exp = "should fail" if unproxied else ("best available" if proxied else "should work")
        m.append(_row("Linear adjustment, each dose level separately", float(slope), truth, exp if clean else "approximate",
                      "" if clean else "straight-line adjustment for curved relationships"))
        gc, se_last = _gcomp_dose(df, Yn, T, rec, out["grid"])
        span = out["grid"][-1] - out["grid"][0]
        sl = (gc[-1] - gc[0]) / span
        m.append(_row("Double ML with dose levels, average slope", (sl, [sl - 1.96 * se_last / span, sl + 1.96 * se_last / span]), truth, "approximate" if exp == "should work" else exp,
                      "flexible, but pulled towards zero when few units sit at the lowest and highest levels"))
        key["targets"][0]["quick_estimate_curve"] = dict(zip([str(g) for g in out["grid"]], gc))
        key["correct_adjustment"] = rec
    elif s["design"] == "cutoff":
        rv = s["cutoff"]["running"]
        m.append(_row("Plain comparison (no adjustment)", _quick_ols(df, Yn, T, []), truth, "should fail", "the programme goes to higher-risk units"))
        m.append(_row(f"Adjust for {rv} with a straight line over the whole range", _quick_ols(df, Yn, T, [rv]), truth, "can mislead"))
        fz = s["cutoff"].get("fuzzy")
        m.append(_row("Local comparison at the cutoff (regression discontinuity)",
                      _boot(lambda q: _local_linear_rd(q, Yn, T, rv, s["cutoff"]["threshold"], s["cutoff"].get("bandwidth"), fuzzy=fz), df), truth, "should work"))
        key["correct_design"] = "Compare units just above and just below the cutoff (regression discontinuity)" + ("; scale by the jump in take-up (fuzzy cutoff)." if fz else ".")
    else:
        m.append(_row("Plain comparison (no adjustment)", _quick_ols(df, Yn, T, []), truth, "should fail" if confounded else "should work"))
        if rec:
            exp = "should fail" if unproxied else ("best available" if proxied else "should work")
            why = "an unrecorded driver remains" if unproxied else ("a recorded column only partly stands in for an unrecorded driver" if proxied else "")
            gaps = bool(df[rec].isna().any().any())
            noisy = d["measurement_error"] and any(v.get("noisy") and v["name"] in rec for v in s["variables"])
            if exp == "should work" and (gaps or noisy):
                exp = "best available"
                why = "the released columns have " + " and ".join(w for w, on in (("gaps", gaps), ("measurement noise", noisy)) if on) + ", so some bias remains"
            m.append(_row("Flexible adjustment for all recorded drivers (doubly robust ML)", _aipw(df, Yn, T, rec), truth, exp, why))
            m.append(_row("Linear adjustment for all recorded drivers", _quick_ols(df, Yn, T, rec), truth,
                          exp if (clean and y.get("type", "continuous") == "continuous") or exp != "should work" else "approximate", "" if clean else "straight lines on curved relationships"))
            if len(rec) > 1:
                m.append(_row(f"Adjust for {rec[0]} only", _quick_ols(df, Yn, T, [rec[0]]), truth, "can mislead", "leaves other drivers out"))
            for v in s["variables"]:
                if v.get("role") == "prior_outcome" and len(rec) > 1:
                    rest = [c for c in rec if c != v["name"]]
                    m.append(_row(f"Leave out {v['name']} (the before-the-action outcome)", _quick_ols(df, Yn, T, rest), truth, "should fail", "misses targeting on past results"))
        for p_ in s["post_treatment"]:
            if p_["name"] in df:
                m.append(_row(f"Also adjust for {p_['name']} ({p_.get('kind', 'consequence')})", _quick_ols(df, Yn, T, rec + [p_["name"]]), truth, "should fail",
                              "controls for a result of the action" if p_.get("kind") != "collider" else "controls for something caused by both the action and the outcome"))
        if s.get("mediator") and s["mediator"]["name"] in df:
            m.append(_row(f"Also adjust for {s['mediator']['name']} (middle step)", _quick_ols(df, Yn, T, rec + [s["mediator"]["name"]]), truth, "should fail",
                          "removes the part of the effect that flows through the middle step"))
        if s.get("instrument"):
            zi = s["instrument"]["name"]
            late = next(t["value"] for t in key["targets"] if t["name"] == "late")
            wald = lambda q: (q.loc[q[zi] == 1, Yn].mean() - q.loc[q[zi] == 0, Yn].mean()) / (q.loc[q[zi] == 1, T].mean() - q.loc[q[zi] == 0, T].mean())
            r = _row("Random-nudge estimate (instrument)", _boot(wald, df), late, "should work", "compare with the compliers' effect, not the average for everyone")
            r["compared_with"] = "late"
            m.append(r)
        key["correct_adjustment"] = rec
    key["true_value_primary"] = truth
    return key


def _gcomp_dose(df, y, t, controls, grid, seed=1):
    """Double ML with the dose as categories: cross-fitted ML residualizes the outcome and each dose
    indicator on the recorded drivers, then a regression of residual on residuals gives the curve."""
    from sklearn.ensemble import HistGradientBoostingRegressor
    X = pd.get_dummies(df[controls], drop_first=True).astype("float64").to_numpy(dtype=float, na_value=np.nan)
    Y = df[y].astype(float).values
    lv = [float(g) for g in grid]
    D = np.column_stack([(df[t].astype(float).values == g).astype(float) for g in lv[1:]])
    n = len(Y)
    fold = np.random.default_rng(seed).integers(0, 2, n)
    kw = dict(max_iter=200, learning_rate=0.05, max_leaf_nodes=15, random_state=seed)
    ry = np.zeros(n); rd = np.zeros_like(D)
    for k in (0, 1):
        tr, te = fold != k, fold == k
        ry[te] = Y[te] - HistGradientBoostingRegressor(**kw).fit(X[tr], Y[tr]).predict(X[te])
        for j in range(D.shape[1]):
            rd[te, j] = D[te, j] - HistGradientBoostingRegressor(**kw).fit(X[tr], D[tr, j]).predict(X[te])
    beta = np.linalg.lstsq(rd, ry, rcond=None)[0]
    e = ry - rd @ beta
    bread = np.linalg.pinv(rd.T @ rd)
    V = bread @ (rd.T * e ** 2) @ rd @ bread
    return [0.0] + [float(b) for b in beta], float(math.sqrt(V[-1, -1]))


def _dose_curve_ols(df, y, t, controls, grid):
    import statsmodels.api as sm
    D = pd.get_dummies(df[t].astype(float).round(6).astype(str), prefix="d").astype(float)
    base = f"d_{float(grid[0])}"
    X = pd.concat([D.drop(columns=[base], errors="ignore"), pd.get_dummies(df[controls], drop_first=True).astype(float)], axis=1)
    X = sm.add_constant(X.fillna(X.median()))
    p = sm.OLS(df[y].astype(float), X).fit().params
    return [0.0 if f"d_{float(g)}" == base else float(p.get(f"d_{float(g)}", np.nan)) for g in grid]


def _local_linear_rd(df, y, t, r, thr, bw=None, fuzzy=False):
    import statsmodels.api as sm
    x = df[r].astype(float) - thr
    bw = bw or 0.25 * x.std()
    w = x.abs() <= bw
    d = pd.DataFrame({"y": df[y].astype(float), "t": df[t].astype(float), "a": (x >= 0).astype(float), "x": x})[w].dropna()
    X = sm.add_constant(pd.DataFrame({"a": d["a"], "x": d["x"], "ax": d["a"] * d["x"]}))
    jy = sm.OLS(d["y"], X).fit().params["a"]
    if not fuzzy:
        return float(jy)
    jt = sm.OLS(d["t"], X).fit().params["a"]
    return float(jy / jt)


# ---------------------------------------------------------------------------- rollout (panel)
def generate_rollout(s, seed):
    rng = np.random.default_rng(seed)
    ro = s["rollout"]
    n, P = int(s["n"]), int(ro["periods"])
    y = s["outcome"]
    heavy = s["dials"]["heavy_tails"]
    U, Z, X, nl = _drivers(s, n, rng)
    fe = _index(s, Z, U, "to_outcome", nl) + rng.standard_normal(n) * y.get("unit_sd", 1.0)
    trend_sel = ro.get("trend_selection", 0.0)  # adopters already on a different path (breaks parallel trends)
    lin = _index(s, Z, U, "to_treat", nl) + ro.get("level_selection", 0.5) * (fe - fe.mean()) / (fe.std() + 1e-9)
    slope = rng.standard_normal(n) * ro.get("slope_sd", 0.0)
    order = np.argsort(-(lin + rng.standard_normal(n) * 0.8))
    share_never = ro.get("never_share", 0.3)
    cohorts = ro.get("cohorts", [P // 2])
    n_adopt = int(n * (1 - share_never))
    adopt = np.full(n, 0)
    chunks = np.array_split(order[:n_adopt], len(cohorts))
    for c, idx in zip(cohorts, chunks):
        adopt[idx] = c
    if trend_sel:
        slope = slope + trend_sel * (adopt > 0) * y.get("noise_sd", 1.0) / P * 3
    season = np.array([ro.get("season_amp", 0.0) * math.sin(2 * math.pi * t / 12) + ro.get("time_trend", 0.0) * t for t in range(P)])
    rows = []
    tau_rows = []
    ate = float(s["effect"]["ate"])
    ramp = ro.get("ramp_periods", 0)
    anticip = ro.get("pre_dip", 0.0)
    for t in range(P):
        k = t - adopt + 1  # periods since adoption (1 = first treated period)
        treated = (adopt > 0) & (t >= adopt)
        eff = np.where(treated, ate * (np.minimum(k, ramp) / ramp if ramp else 1.0), 0.0)
        dip = np.where((adopt > 0) & (t == adopt - 1), anticip, 0.0)
        eps = _noise(n, y.get("noise_sd", 1.0), heavy, rng)
        y0 = y.get("base", 0) + fe + season[t] + slope * t + dip + eps
        yy = _clipy(y0 + eff, y)
        rows.append(pd.DataFrame({"t": t, "unit": np.arange(n), "treated": treated.astype(int), "y": yy}))
        tau_rows.append(_clipy(y0 + eff, y) - _clipy(y0, y))
    long = pd.concat(rows, ignore_index=True)
    tau = np.concatenate(tau_rows)
    uid = s.get("id_col", {"name": "unit_id", "start": 1001})
    df = pd.DataFrame({uid["name"]: long["unit"] + uid.get("start", 1001),
                       ro.get("period_name", "period"): long["t"] + 1})
    for v in s["variables"]:
        df[v["name"]] = np.asarray(X[v["name"]])[long["unit"]]
    df[ro.get("adopt_name", "adopted_in_period")] = np.where(adopt > 0, adopt + 1, 0)[long["unit"]]
    df[s["treatment"]["name"]] = long["treated"]
    df[y["name"]] = _finish(long["y"].values, y)
    truth_df = df.copy()
    df = _apply_realism(s, df, rng, {uid["name"], ro.get("period_name", "period"), s["treatment"]["name"], y["name"], ro.get("adopt_name", "adopted_in_period")})
    att = float(tau[long["treated"].values == 1].mean())
    key = {"targets": [{"name": "att", "label": "Average effect on adopters over their treated periods", "value": att, "primary": True}], "methods": []}
    by_k = {}
    ks = (long["t"].values - adopt[long["unit"].values] + 1)
    for kk in range(1, (ramp or 1) + 3):
        sel = (long["treated"].values == 1) & (ks == kk)
        if sel.any():
            by_k[str(kk)] = float(tau[sel].mean())
    key["targets"].append({"name": "effect_by_periods_since_adoption", "label": "Effect by periods since adoption", "values": by_k})
    Yn, Tn = y["name"], s["treatment"]["name"]
    tp = df.copy()
    tp["_u"] = long["unit"].values
    tp["_t"] = long["t"].values
    tp["_a"] = adopt[long["unit"].values]
    tp["_y"] = truth_df[Yn].values
    tp["_d"] = truth_df[Tn].values
    naive = lambda q: q.loc[q["_d"] == 1, "_y"].mean() - q.loc[q["_d"] == 0, "_y"].mean()
    key["methods"].append(_row("Treated vs untreated periods (plain comparison)", _boot(naive, tp, 100, cluster="_u"), att, "should fail"))
    ba = lambda q: q.loc[(q["_a"] > 0) & (q["_d"] == 1), "_y"].mean() - q.loc[(q["_a"] > 0) & (q["_d"] == 0), "_y"].mean()
    key["methods"].append(_row("Adopters, after vs before", _boot(ba, tp, 100, cluster="_u"), att, "should fail", "picks up time trends and seasonality"))
    tw = lambda q: _twfe(q, "_y", "_d", "_u", "_t")
    stag_ramp = len(cohorts) > 1 and bool(ramp)
    key["methods"].append(_row("Two-way fixed effects regression", _boot(tw, tp, 100, cluster="_u"), att,
                               "should fail" if trend_sel else ("can mislead" if stag_ramp else "should work"),
                               "biased when adoption is staggered and effects grow over time" if stag_ramp else ""))
    if anticip:
        dip = lambda q: _cs_did(q, "_y", "_u", "_t", "_a", base=(1, 1))
        key["methods"].append(_row("Difference-in-differences using only the period right before switching as baseline", _boot(dip, tp, 100, cluster="_u"), att, "should fail",
                                   "units switched right after a bad period, so that baseline is unusually low"))
    cs = lambda q: _cs_did(q, "_y", "_u", "_t", "_a", base=(2, 4) if anticip else (1, 3))
    key["methods"].append(_row("Cohort-by-cohort difference-in-differences vs never-adopters", _boot(cs, tp, 100, cluster="_u"), att,
                               "should fail" if trend_sel else "should work", "adopters were already on a different path" if trend_sel else
                               ("baseline averaged over earlier periods, skipping the dip" if anticip else "baseline averaged over the last few periods before switching")))
    key["true_value_primary"] = att
    key["correct_design"] = "Difference-in-differences comparing each adoption cohort with units that never adopted, before vs after; check pre-adoption trends."
    ren = _names(s)
    df = df.rename(columns=ren)
    key["column_names"] = ren
    return df, key


def _twfe(df, y, t, u, p):
    d = df[[y, t, u, p]].dropna().astype(float)
    yy = d[y] - d.groupby(u)[y].transform("mean") - d.groupby(p)[y].transform("mean") + d[y].mean()
    tt = d[t] - d.groupby(u)[t].transform("mean") - d.groupby(p)[t].transform("mean") + d[t].mean()
    return float((yy * tt).sum() / (tt * tt).sum())


def _cs_did(d, y, u, t, a, base=(1, 3)):
    """Each adoption cohort vs never-adopters; baseline = mean of periods g-base[1] .. g-base[0]."""
    never = d[d[a] == 0]
    num = den = 0.0
    for g in sorted(d.loc[d[a] > 0, a].unique()):
        coh = d[d[a] == g]
        pre = list(range(int(g) - base[1], int(g) - base[0] + 1))
        yb = coh.loc[coh[t].isin(pre), y].mean()
        nb = never.loc[never[t].isin(pre), y].mean()
        post = coh.loc[coh[t] >= g]
        cm = post.groupby(t)[y].mean()
        nm = never.groupby(t)[y].mean()
        w = post.groupby(t).size()
        att = (cm - yb) - (nm.reindex(cm.index) - nb)
        num += float((att * w).sum())
        den += float(w.sum())
    return float(num / den) if den else float("nan")


# ---------------------------------------------------------------------------- brief + key
def brief_md(s, df, ren):
    L = s["level"]
    lines = [f"# Brief (from {s.get('sme', 'the business owner')})", "", f"\"{s['question']}\"" + (f" {s['ask']}" if s.get("ask") else ""), ""]
    unit = s.get("unit", "row")
    if s["design"] == "rollout":
        lines.append(f"## Columns in data.csv (one row per {unit} per {s['rollout'].get('period_label', 'period')})")
    else:
        lines.append(f"## Columns in data.csv (one row per {unit})")
    lines += ["", "| column | what it is | when it's recorded |", "|---|---|---|"]
    meta = {}
    if s.get("id_col"):
        meta[s["id_col"]["name"]] = (s["id_col"].get("meaning", f"{unit} id"), "-")
    if s["design"] == "rollout":
        ro = s["rollout"]
        meta[ro.get("period_name", "period")] = (ro.get("period_meaning", "period number"), "-")
        meta[ro.get("adopt_name", "adopted_in_period")] = (ro.get("adopt_meaning", "period the change started for this unit (0 = never)"), "-")
    for v in s["variables"]:
        meta[v["name"]] = (v.get("meaning", v.get("label", v["name"])), v.get("recorded", "before the action"))
    for key in ("instrument", "mediator", "negative_control"):
        v = s.get(key)
        if v:
            meta[v["name"]] = (v.get("meaning", v.get("label", v["name"])), v.get("recorded", ""))
    for v in s["post_treatment"]:
        meta[v["name"]] = (v.get("meaning", v.get("label", v["name"])), v.get("recorded", "after the action"))
    for v in s.get("_extra_cols", []):
        meta[v["name"]] = (v.get("meaning", v["name"]), v.get("recorded", "before the action"))
    meta[s["treatment"]["name"]] = (s["treatment"].get("meaning", s["treatment"].get("label")), s["treatment"].get("recorded", ""))
    meta[s["outcome"]["name"]] = (s["outcome"].get("meaning", s["outcome"].get("label")), s["outcome"].get("recorded", ""))
    inv = {v: k for k, v in ren.items()}
    for c in df.columns:
        m, r = meta.get(inv.get(c, c), ("", ""))
        lines.append(f"| {c} | {m} | {r} |")
    lines += ["", "## Notes"]
    for nt in s["notes"]:
        lines.append(f"- {nt['text']}")
    lines.append(f"- {s.get('interference_note', 'One ' + unit + ' getting the action does not affect the others.')}")
    lines.append(f"- {s.get('sme_note', 'The person who wrote this is not a data scientist.')}")
    return "\n".join(lines) + "\n"


def generate(scn: dict, level: str = "realistic", dials: dict | None = None, seed: int = 42, n: int | None = None):
    s = resolve(scn, level, dials)
    if n:
        s["n"] = int(n)
    if s["design"] == "rollout":
        df, key = generate_rollout(s, seed)
    else:
        df, key = generate_cross_section(s, seed)
    ren = key.get("column_names", {})
    brief = brief_md(s, df, ren)
    traps = [t for t in s.get("traps", [])]
    key.update({"scenario": s["id"], "title": s.get("title"), "level": level, "seed": seed, "rows": int(len(df)),
                "dials": s["dials"], "fingerprint": fingerprint(df), "design": s["design"],
                "traps": traps,
                "hidden_drivers": [{"name": h["name"], "label": h.get("label", h["name"]), "why": h.get("why", "")} for h in s["hidden"] if h.get("to_treat") and h.get("to_outcome")],
                "note": "Truth computed from each row's potential outcomes (common random numbers). 'methods' are quick linear or textbook estimates on this file, for orientation."})
    return df, brief, _clean(key)


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, float):
        return round(o, 6)
    return o


# ---------------------------------------------------------------------------- this dataset
SCENARIO = json.loads('{\n "id": "saas-pricing-rollout",\n "industry": "SaaS & product",\n "title": "New pricing page rollout \\u2192 trial signups",\n "teaser": "Regions switched in waves; effect builds up; fast-growing regions went first.",\n "question": "Did the new pricing page increase trial signups?",\n "ask": "It went live region by region, so there was no clean A/B test.",\n "sme": "a growth lead",\n "unit": "region",\n "units": "regions",\n "design": "rollout",\n "n": 80,\n "default_level": "realistic",\n "id_col": {\n  "name": "region_id",\n  "start": 1\n },\n "treatment": {\n  "name": "new_pricing_live",\n  "type": "binary",\n  "meaning": "1 = new pricing page live in this region that month",\n  "recorded": "monthly"\n },\n "outcome": {\n  "name": "trial_signups",\n  "type": "continuous",\n  "base": 400,\n  "noise_sd": 25,\n  "unit_sd": 90,\n  "min": 0,\n  "decimals": 0,\n  "meaning": "trial signups that month",\n  "recorded": "monthly"\n },\n "effect": {\n  "ate": 30,\n  "unit_label": "signups per region per month"\n },\n "rollout": {\n  "periods": 18,\n  "cohorts": [\n   8,\n   11,\n   14\n  ],\n  "never_share": 0.3,\n  "ramp_periods": 0,\n  "season_amp": 20,\n  "time_trend": 2,\n  "period_name": "month",\n  "period_label": "month",\n  "period_meaning": "month number (1 = Jan last year)",\n  "adopt_name": "switched_in_month",\n  "adopt_meaning": "month the new page went live here (0 = never)"\n },\n "level_overrides": {\n  "realistic": {\n   "rollout": {\n    "ramp_periods": 4\n   }\n  },\n  "tricky": {\n   "rollout": {\n    "trend_selection": 1.5\n   }\n  },\n  "unanswerable": {\n   "rollout": {\n    "trend_selection": 3.0\n   }\n  }\n },\n "level_dials": {\n  "starter": {\n   "irrelevant": 0\n  },\n  "realistic": {\n   "irrelevant": 0\n  },\n  "tricky": {\n   "irrelevant": 0\n  },\n  "unanswerable": {\n   "irrelevant": 0\n  }\n },\n "variables": [\n  {\n   "name": "market_size_k",\n   "meaning": "addressable businesses in the region (thousands)",\n   "recorded": "fixed",\n   "dist": {\n    "type": "lognormal",\n    "median": 40,\n    "spread": 0.6\n   },\n   "clip": [\n    3,\n    900\n   ],\n   "decimals": 0,\n   "to_treat": 0.5,\n   "to_outcome": 60\n  },\n  {\n   "name": "language",\n   "meaning": "main site language",\n   "recorded": "fixed",\n   "dist": {\n    "type": "category",\n    "levels": [\n     "en",\n     "de",\n     "fr",\n     "es",\n     "pt"\n    ],\n    "probs": [\n     0.4,\n     0.2,\n     0.15,\n     0.15,\n     0.1\n    ]\n   }\n  }\n ],\n "notes": [\n  {\n   "text": "Bigger markets got the new page first."\n  },\n  {\n   "text": "Signups are seasonal (slower in summer)."\n  },\n  {\n   "text": "Marketing says the regions that switched early were already our fastest growing.",\n   "min_level": "tricky"\n  }\n ],\n "traps": [\n  {\n   "name": "Time trends",\n   "text": "Before/after on adopters picks up growth and seasonality."\n  },\n  {\n   "name": "Staggered waves with growing effects",\n   "text": "Two-way fixed effects can mislead when effects build up.",\n   "min_level": "realistic"\n  },\n  {\n   "name": "Different paths",\n   "text": "Regions already growing faster adopted first; parallel trends fail.",\n   "min_level": "tricky"\n  }\n ]\n}')
LEVEL = 'realistic'
DIALS = json.loads('{}')
SEED = 14
N = None

if __name__ == '__main__':
    import argparse, pathlib
    ap = argparse.ArgumentParser(); ap.add_argument('--out', default='.'); a = ap.parse_args()
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    df, brief, key = generate(SCENARIO, LEVEL, DIALS, SEED, N)
    df.to_csv(out / 'data.csv', index=False); (out / 'brief.md').write_text(brief)
    (out / 'answer_key.json').write_text(json.dumps(key, indent=1))
    print(f"wrote {len(df):,} rows, fingerprint {key['fingerprint']}")
