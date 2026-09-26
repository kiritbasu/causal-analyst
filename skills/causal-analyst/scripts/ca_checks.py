"""Checks on the analysis design itself (not just the estimate).

- codebook_draft: a column-by-column sheet for Claude to fill with its reading of each column
  (meaning, when recorded) and for the SME to confirm; guards against misleading names.
- alternative_diagrams: re-estimate under plausible alternative diagrams (SME/Claude-supplied)
  plus automatic leave-one-control-out and add-one-left-out-column variants.
- structure_check: a light PC-style search (Fisher-z partial correlations) used only as a second
  opinion: patterns that suggest a control is a collider or consequence, controls with no link,
  and unused columns linked to both action and outcome. Findings become questions, never edits.
- simulation_check: plant a known effect in the user's own data (real controls, real assignment,
  simulated outcome) and see whether the main method recovers it.
"""
from __future__ import annotations

import itertools
import math

import numpy as np
import pandas as pd

import ca_core as core


# ---------------------------------------------------------------------------- codebook
def codebook_draft(df: pd.DataFrame, treatment=None, outcome=None) -> dict:
    cols = {}
    for c in df.columns:
        s = df[c]
        ex = [None if pd.isna(v) else (v.item() if hasattr(v, "item") else v) for v in s.dropna().unique()[:4]]
        cols[c] = {"type": core._col_kind(s), "examples": ex,
                   "meaning": "", "recorded": "unknown", "confirmed": False,
                   "_hint": "Write what this column most likely is and when it is recorded relative to the action; "
                            "the SME confirms or corrects. Never rely on the name alone."}
    if treatment in cols:
        cols[treatment]["recorded"] = "the action"
    if outcome in cols:
        cols[outcome]["recorded"] = "the outcome"
    return {"columns": cols}


def codebook_status(spec: dict) -> dict:
    """Which columns used in the analysis have an unconfirmed meaning."""
    cb = spec.get("codebook") or {}
    used = [spec["treatment"], spec["outcome"]] + spec.get("confounders", []) + spec.get("instruments", [])
    missing = [c for c in used if c not in cb or not cb[c].get("meaning")]
    unconfirmed = [c for c in used if c in cb and cb[c].get("meaning") and not cb[c].get("confirmed")]
    return {"has_codebook": bool(cb), "no_meaning": missing, "unconfirmed": unconfirmed}


# ---------------------------------------------------------------------------- alternatives
def _quick_aipw(df, T, Y, conf, estimand, seed):
    X = core.design_matrix(df, conf) if conf else np.ones((len(df), 1))
    t = df[T].astype(int).values
    y = df[Y].astype(float).values
    e, m0, m1 = core.crossfit_nuisances(X, t, y, "gbm", 5, seed)
    r = core.aipw(y, t, e, m0, m1, estimand)
    return {"estimate": r["estimate"], "ci": r["ci"]}


def _ols(df, T, Y, conf):
    import statsmodels.api as sm
    Xd = pd.get_dummies(df[[T] + list(conf)], drop_first=True).astype(float)
    Xd = sm.add_constant(Xd.fillna(Xd.median()))
    m = sm.OLS(df[Y].astype(float), Xd).fit(cov_type="HC1")
    ci = m.conf_int().loc[T].tolist()
    return {"estimate": float(m.params[T]), "ci": [float(ci[0]), float(ci[1])]}


def alternative_diagrams(df, spec, seed=1729, id_like=()):
    T, Y = spec["treatment"], spec["outcome"]
    conf = list(spec.get("confounders", []))
    estimand = spec.get("estimand", "ATE")
    out = {"user": [], "leave_one_out": [], "add_one": []}
    base = _ols(df, T, Y, conf)
    out["linear_main_spec"] = base
    for alt in spec.get("alternatives", []):
        c = list(alt.get("confounders", conf))
        c = [x for x in c if x not in alt.get("remove", [])] + [x for x in alt.get("add", []) if x not in c]
        try:
            r = _quick_aipw(df, T, Y, c, estimand, seed)
        except Exception as ex:
            r = {"error": str(ex)[:200]}
        out["user"].append({"name": alt.get("name", "alternative"), "why": alt.get("why", ""), "confounders": c,
                            "illustrative": bool(alt.get("illustrative")), **r})
    for x in conf:
        c = [z for z in conf if z != x]
        r = _ols(df, T, Y, c)
        out["leave_one_out"].append({"column": x, **r, "shift": r["estimate"] - base["estimate"]})
    others = [c for c in df.columns if c not in conf + [T, Y] + list(spec.get("instruments", [])) and c not in id_like
              and df[c].nunique() > 1 and (pd.api.types.is_numeric_dtype(df[c]) or df[c].nunique() <= 20)]
    for x in others[:12]:
        try:
            r = _ols(df, T, Y, conf + [x])
        except Exception:
            continue
        why = spec.get("excluded", {}).get(x, "not used")
        out["add_one"].append({"column": x, "left_out_because": why, **r, "shift": r["estimate"] - base["estimate"]})
    return out


# ---------------------------------------------------------------------------- structure check
def _pcorr_p(C, i, j, S, n):
    idx = [i, j] + list(S)
    sub = C[np.ix_(idx, idx)]
    try:
        P = np.linalg.pinv(sub)
    except Exception:
        return 1.0
    r = -P[0, 1] / math.sqrt(abs(P[0, 0] * P[1, 1])) if P[0, 0] * P[1, 1] > 0 else 0.0
    r = max(min(r, 0.999999), -0.999999)
    z = 0.5 * math.log((1 + r) / (1 - r)) * math.sqrt(max(n - len(S) - 3, 1))
    from scipy.stats import norm
    return float(2 * (1 - norm.cdf(abs(z))))


def structure_check(df, spec, alpha=0.001, max_cond=2, max_vars=14, id_like=()):
    """PC-style skeleton + v-structures on numeric/binary columns (linear-Gaussian tests)."""
    T, Y = spec["treatment"], spec["outcome"]
    conf = list(spec.get("confounders", []))
    excl = list(spec.get("excluded", {}).keys())
    cand = [T, Y] + conf + [c for c in excl if c not in conf] + [c for c in df.columns if c not in [T, Y] + conf + excl]
    cols = []
    for c in cand:
        if c in cols or c in id_like or c not in df:
            continue
        s = df[c]
        if pd.api.types.is_numeric_dtype(s) and s.nunique() > 1:
            cols.append(c)
    cols = cols[:max_vars]
    if T not in cols or Y not in cols:
        return {"skipped": "action or outcome is not numeric"}
    D = df[cols].astype(float).dropna()
    D = D.sample(min(len(D), 20000), random_state=0)
    n = len(D)
    C = np.corrcoef(D.values, rowvar=False)
    k = len(cols)
    adj = {i: set(range(k)) - {i} for i in range(k)}
    sepset = {}
    for size in range(max_cond + 1):
        for i, j in itertools.combinations(range(k), 2):
            if j not in adj[i]:
                continue
            nbrs = (adj[i] | adj[j]) - {i, j}
            for S in itertools.combinations(sorted(nbrs), size):
                if _pcorr_p(C, i, j, S, n) > alpha:
                    adj[i].discard(j); adj[j].discard(i)
                    sepset[(i, j)] = sepset[(j, i)] = set(S)
                    break
    # v-structures i -> m <- j where i, j not adjacent and m not in sepset(i, j)
    vs = []
    for m in range(k):
        for i, j in itertools.combinations(sorted(adj[m]), 2):
            if j not in adj[i] and m not in sepset.get((i, j), set()):
                vs.append((cols[i], cols[m], cols[j]))
    ti, yi = cols.index(T), cols.index(Y)
    edges = sorted({tuple(sorted((cols[i], cols[j]))) for i in range(k) for j in adj[i]})
    findings = []
    for x in conf:
        if x not in cols:
            continue
        xi = cols.index(x)
        into_x = [(a, b) for a, mid, b in vs if mid == x]
        if any({a, b} & {T, Y} for a, b in into_x) and (ti in adj[xi] or yi in adj[xi]):
            findings.append({"column": x, "kind": "possible consequence",
                             "text": f"The data pattern suggests {x} may be affected by other variables rather than only affecting them (a collider-like pattern). Confirm it was recorded before the action and isn't influenced by the outcome."})
        if ti not in adj[xi] and yi not in adj[xi]:
            findings.append({"column": x, "kind": "no link",
                             "text": f"No direct link from {x} to the action or the outcome once other columns are accounted for. Harmless to keep, but it isn't doing much."})
        elif ti in adj[xi] and yi not in adj[xi]:
            findings.append({"column": x, "kind": "action only",
                             "text": f"{x} is linked to who got the action but not directly to the outcome. Fine as a control; if it is close to random it might even serve as a natural experiment."})
    for x in cols:
        if x in conf + [T, Y]:
            continue
        xi = cols.index(x)
        if ti in adj[xi] and yi in adj[xi]:
            why = spec.get("excluded", {}).get(x)
            findings.append({"column": x, "kind": "linked to both",
                             "text": (f"{x} is linked to both the action and the outcome. It was left out on purpose ({why.split(':')[0]}), which fits if it is a consequence of the action; check that reason still holds."
                                      if why else f"{x} is not used, but is linked to both the action and the outcome. Is it a missing control, or a consequence of the action? Ask before running.")})
    return {"method": "PC-style search, Fisher-z partial correlations (linear), alpha 0.001, conditioning sets up to 2",
            "columns": cols, "rows": n, "edges": [list(e) for e in edges], "v_structures": [list(v) for v in vs],
            "findings": findings,
            "note": "A second opinion from the data only. Linear tests on numeric columns; it can miss nonlinear links and cannot see unrecorded factors. Treat findings as questions for the expert."}


# ---------------------------------------------------------------------------- simulation check
def simulation_check(df, spec, planted=None, reps=3, seed=1729):
    """Keep the real controls and the real assignment; simulate the outcome with a known effect."""
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
    T, Y = spec["treatment"], spec["outcome"]
    conf = list(spec.get("confounders", []))
    estimand = spec.get("estimand", "ATE")
    X = core.design_matrix(df, conf) if conf else np.ones((len(df), 1))
    t = df[T].astype(int).values
    y = df[Y].astype(float).values
    binary_y = set(np.unique(y)) <= {0.0, 1.0}
    rng = np.random.default_rng(seed)
    if binary_y:
        m = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_leaf_nodes=15, random_state=seed).fit(X[t == 0], y[t == 0])
        base = m.predict_proba(X)[:, 1]
    else:
        m = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_leaf_nodes=15, random_state=seed).fit(X[t == 0], y[t == 0])
        base = m.predict(X)
        resid = y[t == 0] - m.predict(X[t == 0])
    if planted is None:
        planted = 0.2 * (float(np.std(y)) if not binary_y else 0.25)
    runs = []
    for k in range(reps):
        if binary_y:
            ys = rng.binomial(1, np.clip(base + planted * t, 0, 1)).astype(float)
        else:
            ys = base + planted * t + rng.choice(resid, size=len(y), replace=True)
        e, m0, m1 = core.crossfit_nuisances(X, t, ys, "gbm", 5, seed + k)
        r = core.aipw(ys, t, e, m0, m1, estimand)
        naive = float(ys[t == 1].mean() - ys[t == 0].mean())
        runs.append({"estimate": r["estimate"], "ci": r["ci"], "covers": bool(r["ci"][0] <= planted <= r["ci"][1]), "naive": naive})
    est = [x["estimate"] for x in runs]
    return {"planted": float(planted), "reps": reps, "runs": runs,
            "mean_estimate": float(np.mean(est)), "bias": float(np.mean(est) - planted),
            "coverage": float(np.mean([x["covers"] for x in runs])),
            "naive_mean": float(np.mean([x["naive"] for x in runs])),
            "note": "Real controls and real assignment; outcome simulated from the data's own patterns with a known effect. Tests the method on this data's structure, not hidden factors."}
