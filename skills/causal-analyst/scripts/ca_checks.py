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
    unconfirmed = [c for c in used if c in cb and cb[c].get("meaning") and not cb[c].get("confirmed")
                   and str(cb[c].get("source", "")).lower() not in ("brief", "sme")]
    from_brief = [c for c in used if c in cb and not cb[c].get("confirmed") and str(cb[c].get("source", "")).lower() == "brief"]
    return {"has_codebook": bool(cb), "no_meaning": missing, "unconfirmed": unconfirmed, "from_brief": from_brief}


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
    # Time order as background knowledge: a column recorded before the action can't be caused by the action or
    # the outcome, so a v-structure pointing into it contradicts the timing rather than revealing a consequence.
    cb = spec.get("codebook", {}) or {}
    def _before(c):
        r = str((cb.get(c) or {}).get("recorded", "")).lower()
        return bool(r) and any(w in r for w in ("before", "prior", "baseline", "at sign", "at enrol", "at account", "at hire", "at start", "last year", "previous"))
    edges = sorted({tuple(sorted((cols[i], cols[j]))) for i in range(k) for j in adj[i]})
    findings = []
    for x in conf:
        if x not in cols:
            continue
        xi = cols.index(x)
        into_x = [(a, b) for a, mid, b in vs if mid == x]
        if any({a, b} & {T, Y} for a, b in into_x) and (ti in adj[xi] or yi in adj[xi]):
            if _before(x):
                findings.append({"column": x, "kind": "timing conflict",
                                 "text": f"The linear pattern would make {x} a consequence, but it was recorded before the action ({cb[x].get('recorded')}), so it can't be one. More likely a curved or hidden link; keep it as a control."})
            else:
                findings.append({"column": x, "kind": "possible consequence",
                                 "text": f"The data pattern suggests {x} may be affected by other variables rather than only affecting them (a collider-like pattern). Confirm it was recorded before the action and isn't influenced by the outcome."})
        if ti not in adj[xi] and yi not in adj[xi]:
            findings.append({"column": x, "kind": "no linear link",
                             "text": f"No direct straight-line link from {x} to the action or the outcome was found once other columns are accounted for. Keep it if the expert thinks it matters: these tests miss curved and weak links, and leaving out a real driver costs more than keeping a spare one."})
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
            "note": ("A second opinion from the data only. Linear tests on numeric columns, conditioning on at most two others: it can miss curved links, "
                     "cannot see unrecorded factors, and only spots colliders in simple patterns, so no warning is not proof a column is safe. "
                     "Columns recorded before the action are never treated as consequences. Treat findings as questions for the expert.")}


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
    # The planted effect varies by unit (larger where the baseline is higher), as real effects do, so the check
    # also tests that the method averages over the right people (everyone vs those who got the action).
    z = (base - base.mean()) / (base.std() or 1.0)
    tau = float(planted) * (1 + 0.5 * np.clip(z, -1.5, 1.5))
    target = float(np.mean(tau)) if estimand == "ATE" else float(np.mean(tau[t == 1]))
    if binary_y:
        # probabilities are clipped to [0, 1], so the effect actually planted can be smaller than asked
        p1, p0 = np.clip(base + tau, 0, 1), np.clip(base, 0, 1)
        target = float(np.mean(p1 - p0)) if estimand == "ATE" else float(np.mean((p1 - p0)[t == 1]))
    runs = []
    for k in range(reps):
        if binary_y:
            ys = rng.binomial(1, np.clip(base + tau * t, 0, 1)).astype(float)
        else:
            ys = base + tau * t + rng.choice(resid, size=len(y), replace=True)
        e, m0, m1 = core.crossfit_nuisances(X, t, ys, "gbm", 5, seed + k)
        r = core.aipw(ys, t, e, m0, m1, estimand)
        naive = float(ys[t == 1].mean() - ys[t == 0].mean())
        runs.append({"estimate": r["estimate"], "ci": r["ci"], "covers": bool(r["ci"][0] <= target <= r["ci"][1]), "naive": naive})
    est = [x["estimate"] for x in runs]
    return {"planted": target, "reps": reps, "runs": runs,
            "mean_estimate": float(np.mean(est)), "bias": float(np.mean(est) - target),
            "coverage": float(np.mean([x["covers"] for x in runs])),
            "naive_mean": float(np.mean([x["naive"] for x in runs])),
            "note": "Real controls and real assignment; outcome simulated from the data's own patterns with a known effect that varies across units. Tests the method on this data's structure, not hidden factors."}


# ---------------------------------------------------------------------------- domain checks
def negative_controls(df, spec, seed=1729):
    """Main-method estimate on outcomes the action cannot plausibly affect (chosen before the run
    from domain knowledge). A clear 'effect' there signals hidden bias that also touches the main answer."""
    T = spec["treatment"]
    conf = list(spec.get("confounders", []))
    estimand = spec.get("estimand", "ATE")
    out = []
    for item in spec.get("negative_control_outcomes", []):
        col = item["column"] if isinstance(item, dict) else item
        why = item.get("why", "") if isinstance(item, dict) else ""
        if col not in df:
            out.append({"column": col, "error": "column not found"}); continue
        d = df[[T, col] + conf].dropna()
        try:
            r = _quick_aipw(d, T, col, conf, estimand, seed)
        except Exception as ex:
            out.append({"column": col, "error": str(ex)[:200]}); continue
        base = float(d.loc[d[T] == 0, col].mean())
        lo, hi = r["ci"]
        out.append({"column": col, "why": why, **r, "untreated_mean": base,
                    "relative": (r["estimate"] / base) if base else None,
                    "passes": bool(lo <= 0 <= hi)})
    return out


def calibrate_with_negative_control(main, main_base, nc):
    """Planning figure: remove the relative bias seen on a negative-control outcome from the main
    estimate, assuming the hidden difference shifts both outcomes by the same share. A rough guide,
    reported next to (never instead of) the main result."""
    try:
        m0, b0 = float(main_base), float(nc["untreated_mean"])
        if m0 <= 0 or b0 <= 0:
            return None
        rr_m = (m0 + main["estimate"]) / m0
        rr_n = (b0 + nc["estimate"]) / b0
        if rr_m <= 0 or rr_n <= 0:
            return None
        se_m = (main["ci"][1] - main["ci"][0]) / 3.92 / (m0 + main["estimate"])
        se_n = (nc["ci"][1] - nc["ci"][0]) / 3.92 / (b0 + nc["estimate"])
        x = math.log(rr_m) - math.log(rr_n)
        se = math.hypot(se_m, se_n)
        to_diff = lambda v: m0 * (math.exp(v) - 1)
        # A sensitivity band, not a corrected answer: the hidden difference may shift the main outcome by
        # anywhere from half to one and a half times the share it shifts the check outcome.
        ln, lm = math.log(rr_n), math.log(rr_m)
        band = sorted([to_diff(lm - 0.5 * ln), to_diff(lm - 1.5 * ln)])
        return {"estimate": to_diff(x), "ci": [to_diff(x - 1.96 * se), to_diff(x + 1.96 * se)], "negative_control": nc["column"],
                "band": band, "band_multipliers": [0.5, 1.5],
                "assumption": "The unrecorded difference between the groups shifts the main outcome by 0.5 to 1.5 times the share it shifts the check outcome (the middle value assumes exactly the same share)."}
    except Exception:
        return None


def plausibility(main, expected):
    """Compare the main estimate with a range written into the plan before the run
    (from published evidence or domain knowledge). Never changes the estimate."""
    if not expected or main is None or main.get("estimate") is None:
        return None
    lo, hi = sorted([float(expected["low"]), float(expected["high"])])
    est = main["estimate"]
    width = max(abs(hi), abs(lo), 1e-12)
    inside = lo <= est <= hi
    overlaps = bool(main.get("ci")) and not (main["ci"][1] < lo or main["ci"][0] > hi)
    far = (not inside) and (abs(est) > 2 * max(abs(lo), abs(hi)) or est * (lo + hi) < 0)
    return {"low": lo, "high": hi, "estimate": est, "inside": inside, "range_overlaps": overlaps,
            "far_outside": bool(far), "basis": expected.get("basis", ""), "source": expected.get("source", "general knowledge")}
