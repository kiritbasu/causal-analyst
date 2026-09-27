#!/usr/bin/env python3
"""causal-analyst command line.

  python ca.py profile  --data FILE [--treatment COL] [--outcome COL] --out profile.json
  python ca.py codebook --data FILE --out codebook.json    (draft column meanings for Claude to fill and the SME to confirm)
  python ca.py dag      SPEC.json --outdir DIR               (causal diagram: dag.png, dag.mmd, dag.json)
  python ca.py identify SPEC.json --out identification.json
  python ca.py run      SPEC.json --out results.json      (estimates + diagnostics + trust tier)
  python ca.py figures  results.json --outdir DIR           (forest plot)
  python ca.py report   results.json --narrative narrative.json --out report.html   (the designed HTML report)
  python ca.py power    --baseline 0.14 --lift 0.05 | --sd 12 --lift 3   (randomized-test size)

SPEC.json fields (see references/spec.md):
  data, treatment, outcome, treatment_type ("binary"|"continuous"), contrast {x0,x1},
  estimand ("ATE"|"ATT"), confounders [..], excluded {col: reason}, instruments [..],
  mediators [..], randomized (bool), hidden_confounding ("none_known"|"named_driver"),
  hidden_driver_note, segments [pandas query strings], main_method, budget, seed, labels {col: label}
"""
from __future__ import annotations

import os
# One thread per numeric library: on shared or small machines, oversubscribed OpenMP threads
# made runs 20-30x slower in testing. Override by setting these variables yourself.
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import argparse
import datetime as dt
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import ca_core as core  # noqa: E402
import ca_checks as checks  # noqa: E402
from ca_trust import trust_tier  # noqa: E402

BUD = None  # set by cmd_run; run_binary falls back to 'standard' when used as a library
B_seeds = [3]

BUDGETS = {
    "quick": {"boot": 100, "seeds": 1, "forest": False, "dml": True, "subsets": 3, "sim_reps": 1},
    "standard": {"boot": 200, "seeds": 3, "forest": True, "dml": True, "subsets": 5, "sim_reps": 3},
    "thorough": {"boot": 500, "seeds": 5, "forest": True, "dml": True, "subsets": 10, "sim_reps": 10},
}


def _json(o):
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o))


def log(msg):
    print(f"[ca {time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def _finite(o):
    """NaN / inf are not valid JSON: store them as null."""
    if isinstance(o, dict):
        return {k: _finite(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_finite(v) for v in o]
    if isinstance(o, np.ndarray):
        return _finite(o.tolist())
    if isinstance(o, (float, np.floating)):
        return float(o) if math.isfinite(o) else None
    if isinstance(o, np.integer):
        return int(o)
    return o


def dump(obj, path):
    Path(path).write_text(json.dumps(_finite(obj), indent=1, default=_json, allow_nan=False))
    print(f"wrote {path}")


class SpecError(Exception):
    def __init__(self, msg, hint=""):
        super().__init__(msg)
        self.hint = hint


def fail(msg, hint="", code=2):
    print(json.dumps({"error": msg, "hint": hint}, indent=1))
    sys.exit(code)


YES = {"1", "yes", "y", "true", "t", "treated", "on"}
NO = {"0", "no", "n", "false", "f", "control", "untreated", "off"}


def validate_and_prepare(spec, df):
    """Check the plan against the data before anything runs; recode a yes/no action to 0/1.
    Returns (df, notes). Raises SpecError with a plain-language hint."""
    notes = []
    for k in ("treatment", "outcome", "data"):
        if not spec.get(k):
            raise SpecError(f"The plan has no '{k}'.", "Add it to spec.json (see references/spec.md).")
    if spec.get("budget", "standard") not in BUDGETS:
        raise SpecError(f"Unknown budget '{spec.get('budget')}'.", f"Use one of: {', '.join(BUDGETS)}.")
    if spec.get("estimand", "ATE") not in ("ATE", "ATT"):
        raise SpecError(f"Unknown estimand '{spec.get('estimand')}'.", "Use ATE (everyone) or ATT (those who got the action).")
    used = [spec["treatment"], spec["outcome"]] + spec.get("confounders", []) + spec.get("instruments", []) + spec.get("mediators", [])
    missing = [c for c in dict.fromkeys(used) if c not in df.columns]
    if missing:
        raise SpecError(f"Column(s) not in the data: {', '.join(missing)}.", "Check spelling and case against the file's header.")
    T, Y = spec["treatment"], spec["outcome"]
    if not pd.api.types.is_numeric_dtype(df[Y]):
        yv = df[Y].dropna().astype(str).str.strip().str.lower()
        if set(yv.unique()) <= (YES | NO):
            df[Y] = df[Y].map(lambda v: None if pd.isna(v) else (1 if str(v).strip().lower() in YES else 0))
            notes.append(f"Outcome '{Y}' recoded: yes/true = 1, no/false = 0.")
        else:
            raise SpecError(f"The outcome '{Y}' isn't numeric.", "Use a number or a yes/no column as the outcome.")
    if spec.get("treatment_type", "binary") == "continuous":
        if not spec.get("contrast") or not {"x0", "x1"} <= set(spec["contrast"]):
            raise SpecError("An amount action needs a 'contrast' with x0 and x1 (the two levels to compare).", "E.g. \"contrast\": {\"x0\": 0, \"x1\": 10}.")
        if not pd.api.types.is_numeric_dtype(df[T]):
            raise SpecError(f"The amount action '{T}' isn't numeric.", "Use a numeric column, or treat it as yes/no.")
        return df, notes
    vals = df[T].dropna().unique()
    if len(vals) != 2:
        raise SpecError(f"The action '{T}' has {len(vals)} distinct values ({', '.join(map(str, vals[:6]))}{'...' if len(vals) > 6 else ''}); a yes/no analysis needs exactly 2.",
                        "Recode it to two groups, or use treatment_type 'continuous' with a contrast for an amount.")
    tv = spec.get("treated_value")
    sv = {str(v).strip().lower() for v in vals}
    if tv is not None:
        if str(tv) not in {str(v) for v in vals}:
            raise SpecError(f"treated_value '{tv}' is not one of the action's values {list(vals)}.")
        treated = lambda v: str(v) == str(tv)
    elif sv <= {"0", "1", "0.0", "1.0"}:
        treated = lambda v: float(v) == 1.0
    elif sv <= (YES | NO) and sv & YES and sv & NO:
        treated = lambda v: str(v).strip().lower() in YES
    else:
        hi = max(vals, key=lambda v: (str(type(v)), v))
        treated = lambda v: v == hi
        notes.append(f"Action '{T}' has values {list(vals)}; treating '{hi}' as 'got the action'. Set treated_value in the plan to change this.")
    df[T] = df[T].map(lambda v: None if pd.isna(v) else int(treated(v)))
    counts = df[T].value_counts()
    small = int(counts.min()) if len(counts) == 2 else 0
    if small < 10:
        raise SpecError(f"Only {small} rows in the smaller group of '{T}'.", "At least 10 in each group are needed to run anything; 100+ for a trustworthy answer.")
    if small < 100:
        notes.append(f"small_group:{small}")
    return df, notes


def label(spec, col):
    return spec.get("labels", {}).get(col, col)


# ----------------------------------------------------------------------------
def cmd_profile(a):
    df = core.load_data(a.data)
    prof = core.profile(df, a.treatment, a.outcome)
    prof["fingerprint"] = core.file_fingerprint(a.data)
    prof["file"] = a.data
    dump(prof, a.out)
    print(json.dumps({"rows": prof["rows"], "fingerprint": prof["fingerprint"], "flags": prof["flags"]}, indent=1, default=_json))


# ----------------------------------------------------------------------------
def identify(spec) -> dict:
    T, Y = spec["treatment"], spec["outcome"]
    conf = spec.get("confounders", [])
    ivs = spec.get("instruments", [])
    meds = spec.get("mediators", [])
    hidden = spec.get("hidden_confounding", "none_known")
    out = {"treatment": T, "outcome": Y, "estimand": spec.get("estimand", "ATE"), "assumptions": []}

    if spec.get("randomized"):
        out.update(identifiable=True, strategy="randomized", adjustment_set=conf,
                   explanation="Treatment was randomly assigned, so a comparison of groups identifies the effect. Controls are optional and only sharpen precision.")
        out["assumptions"].append("Randomization was actually followed (check balance).")
        return _dowhy_check(spec, out)

    if hidden == "named_driver":
        if meds:
            out.update(identifiable=True, strategy="front-door", adjustment_set=[], mediators=meds,
                       explanation="An unrecorded driver affects both treatment and outcome, but the whole effect flows through a measured middle step that the driver does not touch, so the front-door route identifies it.")
            out["assumptions"] += ["The effect passes entirely through the measured middle step.", "The hidden driver does not affect the middle step directly."]
        elif ivs:
            out.update(identifiable=False, strategy="instrument (complier effect only)", adjustment_set=[], instruments=ivs,
                       explanation="An unrecorded driver affects both treatment and outcome, so adjusting for recorded traits cannot remove the bias. The instrument identifies the effect only for units whose treatment the instrument actually moved (a complier effect), not the average effect for everyone. We report that complier effect and bounds on the average effect instead of a single number.")
            out["assumptions"] += ["The instrument affects the outcome only through the treatment.", "The instrument is as good as randomly assigned."]
        else:
            out.update(identifiable=False, strategy="none", adjustment_set=conf,
                       explanation="An unrecorded driver affects both treatment and outcome, and there is no instrument or clean middle step. No method can remove that bias from this data. We report the adjusted estimate only as a biased reference point, with a sensitivity analysis showing how strong the hidden driver would need to be.")
        return _dowhy_check(spec, out)

    out.update(identifiable=True, strategy="adjust for measured confounders (backdoor)", adjustment_set=conf,
               explanation="Comparing like with like on the recorded pre-treatment traits identifies the effect, provided nothing important that drives both treatment and outcome is missing from the data.")
    if not spec.get("outcome_baseline"):
        out["assumptions"].append("Earlier values of the outcome did not drive who got the treatment (no before-the-action measure of the outcome was named, so reverse causation can't be ruled out by adjustment).")
    elif spec["outcome_baseline"] not in conf:
        out["assumptions"].append(f"The earlier outcome measure '{spec['outcome_baseline']}' should be a control but is not in the controls.")
    out["assumptions"] += [
        "All controls were measured before the treatment (none are consequences of it).",
        "No important unrecorded factor drives both treatment and outcome (cannot be checked; will be sized).",
        "Every kind of unit has some treated and some untreated examples (overlap; will be checked).",
        "One unit's treatment does not change another unit's outcome.",
    ]
    return _dowhy_check(spec, out)


def _dowhy_check(spec, out):
    """Cross-check the rule-based answer with DoWhy's identification engine."""
    try:
        import networkx as nx
        from dowhy import CausalModel

        import ca_dag
        T, Y = spec["treatment"], spec["outcome"]
        dag = ca_dag.build(spec)
        g = ca_dag.analysis_graph(dag)
        nodes = list(g.nodes)
        cols = [n for n in nodes if n != "U_hidden"]
        dummy = pd.DataFrame(np.random.default_rng(0).normal(size=(50, len(cols))), columns=cols)
        dummy[T] = (dummy[T] > 0).astype(int)
        gml = "\n".join(nx.generate_gml(g))
        m = CausalModel(data=dummy, treatment=T, outcome=Y, graph=gml)
        est = m.identify_effect(proceed_when_unidentifiable=False)
        bd = est.get_backdoor_variables() if hasattr(est, "get_backdoor_variables") else None
        if spec.get("extra_edges") and bd is not None and set(bd) != set(spec.get("confounders", [])) and out.get("strategy", "").startswith("adjust"):
            out["assumptions"].append(f"With the arrows added to the diagram, the controls that block every back-door path are {sorted(bd)}; the spec lists {sorted(spec.get('confounders', []))}. Reconcile before running.")
        out["dowhy"] = {"backdoor_variables": bd, "instruments": est.get_instrumental_variables(),
                        "frontdoor": est.get_frontdoor_variables(), "estimand": str(est).split("\n")[:12]}
    except Exception as e:  # identification check is advisory
        out["dowhy"] = {"error": str(e)[:300]}
    return out


def cmd_dag(a):
    import ca_dag
    spec = json.loads(Path(a.spec).read_text())
    dag = ca_dag.write_all(spec, a.outdir)
    print(json.dumps({"wrote": [str(Path(a.outdir) / f) for f in ("dag.png", "dag.mmd", "dag.json")], "warnings": dag["warnings"]}, indent=1))


def cmd_identify(a):
    spec = json.loads(Path(a.spec).read_text())
    r = identify(spec)
    dump(r, a.out)
    print(json.dumps({k: r.get(k) for k in ("identifiable", "strategy", "adjustment_set", "explanation")}, indent=1))


# ----------------------------------------------------------------------------
def run_binary(df, spec, B):
    global BUD
    if BUD is None:
        BUD = BUDGETS[spec.get("budget", "standard")]
    T, Y = spec["treatment"], spec["outcome"]
    conf = spec.get("confounders", [])
    estimand = spec.get("estimand", "ATE")
    seed = int(spec.get("seed", 1729))
    y = df[Y].astype(float).values
    t = df[T].astype(int).values
    X = core.design_matrix(df, conf)
    n = len(y)
    res, timings = {}, {}

    def timed(name, fn):
        log(f"estimating: {name}")
        s = time.time()
        try:
            res[name] = fn()
        except Exception as e:
            res[name] = {"error": str(e)[:300]}
        timings[name] = round(time.time() - s, 1)

    timed("naive_difference", lambda: {k: v for k, v in core.naive_diff(y, t).items()})

    def _ra(lrn):
        est = core.reg_adjust(y, t, X, estimand, lrn, seed)
        bs = core.bootstrap(lambda idx: core.reg_adjust(y[idx], t[idx], X[idx], estimand, lrn, seed), n, B, seed)
        return {"estimate": est, **bs}
    timed("regression_linear", lambda: _ra("linear"))

    # AIPW with gradient boosting, repeated cross-fitting over seeds
    seeds = [seed + k for k in range(B_seeds[0])]
    fits = []
    def _aipw():
        for s in seeds:
            e, m0, m1 = core.crossfit_nuisances(X, t, y, "gbm", 5, s)
            fits.append((e, m0, m1, core.aipw(y, t, e, m0, m1, estimand)))
        ests = np.array([f[3]["estimate"] for f in fits])
        ses = np.array([f[3]["se"] for f in fits])
        k = int(np.argsort(ests)[len(ests) // 2])
        med = float(np.median(ests))
        se = float(math.sqrt(np.median(ses ** 2 + (ests - med) ** 2)))
        return {"estimate": med, "se": se, "ci": [med - 1.96 * se, med + 1.96 * se], "per_seed": ests.tolist(), "_k": k}
    timed("aipw_gbm", _aipw)

    def _aipw_spline():
        e, m0, m1 = core.crossfit_nuisances(X, t, y, "spline", 5, seed)
        r = core.aipw(y, t, e, m0, m1, estimand)
        r.pop("pseudo_outcomes")
        return r
    timed("aipw_spline", _aipw_spline)

    if fits:
        e, m0, m1, a0 = fits[res["aipw_gbm"].get("_k", 0)]
        def _ipw():
            est = core.ipw_hajek(y, t, e, estimand)
            bs = core.bootstrap(lambda idx: core.ipw_refit(y[idx], t[idx], X[idx], estimand, seed), n, min(B, 60), seed)
            # range centred on the estimate, with the spread from refitting the weights each time
            return {"estimate": est, "se": bs["se"], "ci": [est - 1.96 * bs["se"], est + 1.96 * bs["se"]], "n_boot": bs["n_boot"]}
        timed("ipw_gbm", _ipw)
        timed("regression_gbm", lambda: {"estimate": float((m1 - m0)[t == 1].mean() if estimand == "ATT" else (m1 - m0).mean())})
    if BUD["dml"] and estimand == "ATE":
        timed("double_ml", lambda: core.dml_linear(y, t, X, seed))
    cf = None
    if BUD["forest"] and estimand == "ATE" and len(conf) > 0:
        def _cf():
            r = core.causal_forest(y, t, X, seed)
            nonlocal cf
            cf = r.pop("cate")
            return r
        timed("causal_forest", _cf)

    # Optional foundation-model cross-checks. Never the main method; shown next to it.
    optional = {}
    ok, info = core.causalpfn_available()
    if not ok:
        optional["causalpfn"] = {"skipped": info}
    elif estimand != "ATE":
        optional["causalpfn"] = {"skipped": "CausalPFN cross-check covers the everyone-average (ATE) only"}
    elif n > int(spec.get("causalpfn_max_rows", 20000)):
        optional["causalpfn"] = {"skipped": f"{n} rows is slow on CPU; raise causalpfn_max_rows to run it"}
    else:
        timed("causalpfn", lambda: {k: v for k, v in core.causalpfn_ate(X, t, y).items() if k != "cate"})
        optional["causalpfn"] = {"ran": "causalpfn" in res and "error" not in res["causalpfn"], "weights": Path(str(info)).name}
    ok, mode, why = core.tabpfn_available("tabpfn_api" in spec.get("allow_external_services", []))
    if ok:
        timed("aipw_tabpfn", lambda: core.aipw_tabpfn(X, t, y, estimand, 5, seed))
        optional["tabpfn"] = {"ran": "error" not in res.get("aipw_tabpfn", {}), "mode": mode}
    else:
        optional["tabpfn"] = {"skipped": why}

    diag = {"optional_cross_checks": optional}
    log("diagnostics: overlap, balance, shuffled action, random common cause, subsets")
    if fits:
        e, m0, m1, a0 = fits[res["aipw_gbm"].get("_k", 0)]
        psi = a0["pseudo_outcomes"]
        diag["overlap"] = {
            "propensity_quantiles": {q: float(np.quantile(e, q)) for q in (0, 0.01, 0.05, 0.5, 0.95, 0.99, 1)},
            "share_below_0.05": float((e < 0.05).mean()), "share_above_0.95": float((e > 0.95).mean()),
        }
        edges = np.linspace(0, 1, 21)
        diag["overlap"]["histogram"] = {"bin_edges": edges.tolist(),
                                        "treated": np.histogram(e[t == 1], edges)[0].tolist(),
                                        "untreated": np.histogram(e[t == 0], edges)[0].tolist()}
        keep = (e >= 0.05) & (e <= 0.95)
        if keep.mean() < 0.999:
            tr = core.aipw(y[keep], t[keep], e[keep], m0[keep], m1[keep], estimand)
            diag["overlap"]["trimmed_estimate"] = {"estimate": tr["estimate"], "ci": tr["ci"], "share_kept": float(keep.mean()), "note": "effect among units with propensity 0.05-0.95 (a narrower population)"}
        w = np.where(t == 1, 1 / core._clip(e), 1 / (1 - core._clip(e))) if estimand == "ATE" else np.where(t == 1, 1.0, core._clip(e) / (1 - core._clip(e)))
        bal = []
        for j, c in enumerate(pd.get_dummies(df[conf], drop_first=True).columns if conf else []):
            xj = X[:, j]
            bal.append({"variable": c, "smd_before": core.smd(xj, t), "smd_after_weighting": core.smd(xj, t, w)})
        diag["balance"] = bal
        diag["max_abs_smd_after"] = max([abs(b["smd_after_weighting"]) for b in bal], default=0.0)
        # placebo: permuted treatment should give ~0
        # 5 independent shuffles; pass unless their average sits > 3 standard errors from zero
        # (a single shuffle fails 1 time in 20 by chance alone)
        r = np.random.default_rng(seed)
        pls = []
        for k in range(5):
            tp = r.permutation(t)
            ep, m0p, m1p = core.crossfit_nuisances(X, tp, y, "linear", 5, seed + k)
            pls.append(core.aipw(y, tp, ep, m0p, m1p, estimand))
        pm = float(np.mean([p_["estimate"] for p_ in pls]))
        pse = float(np.mean([p_["se"] for p_ in pls]) / math.sqrt(len(pls)))
        diag["placebo_permuted_treatment"] = {"estimate": pm, "ci": [pm - 1.96 * pse, pm + 1.96 * pse], "shuffles": [p_["estimate"] for p_ in pls],
                                              "passes": bool(abs(pm) <= 3 * pse)}
        # random common cause
        Xr = np.column_stack([X, r.normal(size=n)])
        er, m0r, m1r = core.crossfit_nuisances(Xr, t, y, "gbm", 5, seed)
        rc = core.aipw(y, t, er, m0r, m1r, estimand)["estimate"]
        diag["random_common_cause"] = {"estimate": rc, "change": rc - a0["estimate"]}
        # subset stability
        subs = []
        for k in range(BUD["subsets"]):
            idx = r.choice(n, int(0.8 * n), replace=False)
            es, m0s, m1s = core.crossfit_nuisances(X[idx], t[idx], y[idx], "gbm", 5, seed + k)
            subs.append(core.aipw(y[idx], t[idx], es, m0s, m1s, estimand)["estimate"])
        diag["subset_80pct_estimates"] = subs
        # segments (heterogeneity) from AIPW pseudo-outcomes (ATE scale)
        if spec.get("segments") and estimand == "ATE":
            from scipy.stats import norm
            segs = []
            k = max(len(spec["segments"]), 1)
            z_adj = float(norm.ppf(1 - 0.05 / (2 * k)))  # Bonferroni: simultaneous 95% across the k group comparisons
            for q in spec["segments"]:
                try:
                    mask = df.eval(q).values.astype(bool)
                except Exception as ex:
                    segs.append({"segment": q, "error": str(ex)[:200]}); continue
                if min(mask.sum(), (~mask).sum()) < 20:
                    segs.append({"segment": q, "error": f"too few rows on one side ({int(mask.sum())} vs {int((~mask).sum())}); needs 20+ each"}); continue
                for name, mm in ((q, mask), (f"not ({q})", ~mask)):
                    v = psi[mm]
                    segs.append({"segment": name, "n": int(mm.sum()), "estimate": float(v.mean()), "ci": [float(v.mean() - 1.96 * v.std(ddof=1) / math.sqrt(len(v))), float(v.mean() + 1.96 * v.std(ddof=1) / math.sqrt(len(v)))]})
                d = psi[mask].mean() - psi[~mask].mean()
                sd = math.sqrt(psi[mask].var(ddof=1) / mask.sum() + psi[~mask].var(ddof=1) / (~mask).sum())
                segs.append({"segment": f"difference: ({q}) minus rest", "estimate": float(d), "ci": [float(d - 1.96 * sd), float(d + 1.96 * sd)],
                             "ci_adjusted": [float(d - z_adj * sd), float(d + z_adj * sd)], "comparisons_tested": k,
                             "p_value": float(2 * (1 - norm.cdf(abs(d) / sd))) if sd > 0 else None})
            diag["segments"] = segs
        if cf is not None:
            diag["forest_cate_spread"] = {"p10": float(np.percentile(cf, 10)), "p50": float(np.percentile(cf, 50)), "p90": float(np.percentile(cf, 90)), "share_positive": float((cf > 0).mean())}
        res["aipw_gbm"].pop("_k", None)
    if conf:
        try:
            diag["sensitivity"] = core.ols_sensitivity(df, T, Y, conf)
        except Exception as ex:
            diag["sensitivity"] = {"error": str(ex)[:200]}
    return res, diag, timings


def run_continuous(df, spec, B):
    T, Y = spec["treatment"], spec["outcome"]
    conf = spec.get("confounders", [])
    x0, x1 = spec["contrast"]["x0"], spec["contrast"]["x1"]
    seed = int(spec.get("seed", 1729))
    res, timings, cv = {}, {}, {}
    for lrn in ["linear", "spline5", "spline8", "spline12", "gbm"]:
        s = time.time()
        try:
            est, _ = core.dose_contrast(df, T, Y, conf, x0, x1, lrn, seed)
            cv[lrn] = core.cv_score(df, T, Y, conf, lrn, seed)
            res[f"gcomp_{lrn}"] = {"estimate": est, "cv_mse": cv[lrn]}
        except Exception as e:
            res[f"gcomp_{lrn}"] = {"error": str(e)[:200]}
        timings[f"gcomp_{lrn}"] = round(time.time() - s, 1)
    if not cv:
        errs = "; ".join(f"{k}: {v['error']}" for k, v in res.items() if "error" in v)
        raise SystemExit(json.dumps({"error": "Every outcome model failed.", "details": errs[:600]}, indent=1))
    best = min(cv, key=cv.get)
    n = len(df)
    bs = core.bootstrap(lambda idx: core.dose_contrast(df.iloc[idx], T, Y, conf, x0, x1, best, seed)[0], n, B, seed)
    res[f"gcomp_{best}"].update(bs)
    diag = {"model_selection": {"rule": "main outcome model chosen by 5-fold cross-validated error, fixed before looking at effects", "cv_mse": cv, "chosen": best},
            "support": {"x0_percentile": float((df[T] <= x0).mean()), "x1_percentile": float((df[T] <= x1).mean())}}
    return res, diag, timings, f"gcomp_{best}"


def missing_by_arm(df, spec, cols):
    """Share of missing values in each used column, with and without the action (binary actions only)."""
    T = spec["treatment"]
    if spec.get("treatment_type", "binary") == "continuous" or df[T].isna().any():
        return None
    tt = df[T] == 1
    out = []
    for c in cols:
        if c == T or not df[c].isna().any():
            continue
        a1, a0 = float(df.loc[tt, c].isna().mean()), float(df.loc[~tt, c].isna().mean())
        out.append({"column": c, "share_with_action": a1, "share_without": a0, "gap_points": round(100 * abs(a1 - a0), 1)})
    return sorted(out, key=lambda r: -r["gap_points"])


def cmd_run(a):
    spec = json.loads(Path(a.spec).read_text())
    global BUD, B_seeds
    t0 = time.time()
    try:
        df = core.load_data(spec["data"])
        df, prep_notes = validate_and_prepare(spec, df)
    except SpecError as ex:
        fail(str(ex), ex.hint)
    except FileNotFoundError:
        fail(f"Data file not found: {spec['data']}", "Check the 'data' path in the plan (relative to where you run the command).")
    except KeyError as ex:
        fail(f"The plan is missing {ex}.", "Required: data, treatment, outcome.")
    BUD = BUDGETS[spec.get("budget", "standard")]
    B_seeds = [BUD["seeds"]]
    log(f"budget {spec.get('budget', 'standard')}; progress lines follow. Typical: quick <1 min, standard 1-2 min on ~5k rows")
    for nt in prep_notes:
        if not nt.startswith("small_group:"):
            log(nt)
    overview = core.data_overview(df, spec, int(spec.get("report_sample_rows", 5)))
    cols = [spec["treatment"], spec["outcome"]] + spec.get("confounders", []) + spec.get("instruments", [])
    before = len(df)
    miss = missing_by_arm(df, spec, cols)
    df = df.dropna(subset=cols).reset_index(drop=True)
    ident = identify(spec)
    import ca_dag
    _dag = ca_dag.build(spec); _dag["warnings"] = ca_dag.checks(_dag)
    out = {"spec": spec, "dag": _dag, "data_overview": overview, "identification": ident, "rows_used": len(df), "rows_dropped_missing": before - len(df)}
    if spec.get("treatment_type", "binary") == "continuous":
        res, diag, timings, main_key = run_continuous(df, spec, BUD["boot"])
    else:
        res, diag, timings = run_binary(df, spec, BUD["boot"])
        main_key = spec.get("main_method", "aipw_gbm")
        if ident.get("strategy") == "front-door":
            M = spec["mediators"][0]
            log("estimating: front-door (effect through the middle step)")
            s0 = time.time()
            try:
                seed = int(spec.get("seed", 1729))
                est = core.front_door(df, spec["treatment"], M, spec["outcome"], spec.get("confounders", []), seed)
                Bfd = {"quick": 20, "standard": 40, "thorough": 100}[spec.get("budget", "standard")]
                bs = core.bootstrap(lambda idx: core.front_door(df.iloc[idx].reset_index(drop=True), spec["treatment"], M, spec["outcome"], spec.get("confounders", []), seed, draws=8), len(df), Bfd, seed)
                res["front_door"] = {"estimate": est, **bs}
            except Exception as ex:
                res["front_door"] = {"error": str(ex)[:300]}
            timings["front_door"] = round(time.time() - s0, 1)
            main_key = "front_door"
    if spec.get("instruments"):
        z = spec["instruments"][0]
        try:
            diag["instrument"] = {"complier_effect_2sls": core.iv_2sls(df, spec["treatment"], spec["outcome"], z, [c for c in spec.get("confounders", []) if c != z])}
            if df[spec["treatment"]].nunique() == 2:
                diag["instrument"]["bounds_on_average_effect"] = core.iv_bounds_binary(df, spec["treatment"], spec["outcome"], z)
        except Exception as e:
            diag["instrument"] = {"error": str(e)[:200]}
    binary_t = df[spec["treatment"]].nunique() == 2
    if not ident.get("identifiable") and binary_t and not spec.get("instruments"):
        diag["bounds_no_instrument"] = core.bounds_no_instrument(df[spec["outcome"]].values, df[spec["treatment"]].values,
                                                                 spec.get("outcome_range", [None, None])[0], spec.get("outcome_range", [None, None])[1])
    bad = [c for c, why in spec.get("excluded", {}).items() if "post" in str(why).lower() and c in df.columns]
    if bad and spec.get("confounders"):
        try:
            diag["bad_control_illustration"] = core.bad_control_illustration(df, spec["treatment"], spec["outcome"], spec["confounders"], bad)
        except Exception as e:
            diag["bad_control_illustration"] = {"error": str(e)[:200]}
    if spec.get("mediators") and ident.get("strategy") == "front-door":
        diag["note_frontdoor"] = "Front-door estimation is not automated in this version; report identification and ask for analyst review."
    # Ready-made ratios for the report, so no one has to do arithmetic by hand.
    naive = res.get("naive_difference", {}).get("estimate")
    mest = (res.get(main_key) or {}).get("estimate")
    derived = {}
    if naive and mest is not None and ident.get("identifiable"):
        derived["share_of_raw_gap_from_selection"] = float(1 - mest / naive)
    sens = diag.get("sensitivity", {})
    if sens.get("strongest_measured"):
        derived["hidden_factor_strength_needed_vs_strongest_measured"] = float(sens["robustness_value"] / sens["strongest_measured"]["strength"]) if sens["strongest_measured"]["strength"] else None
    y_all = df[spec["outcome"]].astype(float)
    derived["outcome_sd"] = float(y_all.std())
    if df[spec["treatment"]].nunique() == 2:
        tt = df[spec["treatment"]] == df[spec["treatment"]].max()
        derived["outcome_mean_treated"] = float(y_all[tt].mean()); derived["outcome_mean_untreated"] = float(y_all[~tt].mean())
        _m = (res.get(main_key) or {}).get("estimate")
        if _m is not None and derived["outcome_mean_untreated"]:
            derived["effect_relative_to_untreated"] = float(_m / derived["outcome_mean_untreated"])
    diag["derived"] = derived
    # checks on the design itself
    binary_t = df[spec["treatment"]].nunique() == 2
    id_like = [c["column"] for c in overview["column_info"] if c["n_unique"] == overview["rows"] and c["kind"] in ("number", "text/id")]
    diag["codebook"] = checks.codebook_status(spec)
    if binary_t:
        log("design checks: alternative diagrams, structure check")
        try:
            diag["alternatives"] = checks.alternative_diagrams(df, spec, int(spec.get("seed", 1729)), id_like)
        except Exception as ex:
            diag["alternatives"] = {"error": str(ex)[:200]}
        try:
            diag["structure_check"] = checks.structure_check(df, spec, id_like=id_like)
        except Exception as ex:
            diag["structure_check"] = {"error": str(ex)[:200]}
        if ident.get("identifiable") and BUD.get("sim_reps") and (res.get(main_key) or {}).get("estimate") is not None:
            log("simulation check: planting a known effect in your data")
            m = res[main_key]["estimate"]
            planted = float(f"{m:.2g}") if m else None
            try:
                diag["simulation_check"] = checks.simulation_check(df, spec, planted, BUD["sim_reps"], int(spec.get("seed", 1729)))
            except Exception as ex:
                diag["simulation_check"] = {"error": str(ex)[:200]}

    if spec.get("negative_control_outcomes") and binary_t:
        log("domain checks: negative-control outcomes")
        try:
            diag["negative_controls"] = checks.negative_controls(df, spec, int(spec.get("seed", 1729)))
            base_m = diag.get("derived", {}).get("outcome_mean_untreated")
            failed = [x for x in diag["negative_controls"] if "estimate" in x and not x.get("passes")]
            if failed and (res.get(main_key) or {}).get("ci") and base_m:
                cal = checks.calibrate_with_negative_control(res[main_key], base_m, failed[0])
                if cal:
                    diag["negative_control_adjusted"] = cal
        except Exception as ex:
            diag["negative_controls"] = [{"error": str(ex)[:200]}]
    if spec.get("expected_effect"):
        diag["plausibility"] = checks.plausibility(res.get(main_key), spec["expected_effect"])
    if spec.get("domain_notes"):
        diag["domain_notes"] = spec["domain_notes"]
    if miss:
        diag["missing_by_arm"] = miss
    small = [nt for nt in prep_notes if nt.startswith("small_group:")]
    if small:
        spec["_small_group"] = int(small[0].split(":")[1])
    tier, reasons = trust_tier(ident, res, diag, main_key, spec)
    spec.pop("_small_group", None)
    main_failed = bool(reasons) and reasons[0].startswith("The main method (")
    dropped = out["rows_dropped_missing"]
    uneven = [m_ for m_ in (miss or []) if m_["gap_points"] >= 5]
    if uneven:
        w = uneven[0]
        reasons.append(f"'{w['column']}' is missing for {w['share_with_action']:.0%} of rows with the action and {w['share_without']:.0%} without. "
                       "Gaps that differ by group can bias the answer; ask why they are missing.")
        if w["column"] == spec["outcome"] and w["gap_points"] >= 10 and tier in ("A", "B"):
            tier = "C"
            reasons.append("The outcome is missing much more often in one group, so the rows kept are not comparable: grade capped at C.")
    if dropped and dropped / (dropped + out["rows_used"]) > 0.05:
        reasons.append(f"{dropped:,} rows ({100 * dropped / (dropped + out['rows_used']):.0f}%) were left out because a column used had a missing value. If values are missing for a reason linked to the action or the outcome, the answer can shift.")
    main_result = res.get(main_key)
    if main_failed:
        main_key, main_result = None, None
    if not ident.get("identifiable"):
        # Never present a single number for a question the data cannot answer.
        main_key, main_result = None, None
        reasons.append("Adjusted estimates in 'estimates' (and any segment effects) are biased reference points only; do not report them as the answer.")
        if "segments" in diag:
            diag["segments_note"] = "Tier D: segment effects share the same hidden bias; reference only."
    out.update(main_method=main_key, main_result=main_result, estimates=res, diagnostics=diag,
               trust_tier=tier, trust_reasons=reasons, timings_sec=timings,
               manifest={"fingerprint": core.file_fingerprint(spec["data"]), "seed": spec.get("seed", 1729), "budget": spec.get("budget", "standard"),
                         "versions": core.versions(), "run_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "runtime_sec": round(time.time() - t0, 1)})
    for v in res.values():
        if isinstance(v, dict):
            v.pop("pseudo_outcomes", None)
    dump(out, a.out)
    mr = out["main_result"] or {}
    if mr.get("pseudo_outcomes") is not None:
        mr.pop("pseudo_outcomes")
    summary = {"identifiable": ident["identifiable"], "strategy": ident["strategy"], "main_method": main_key,
               "estimate": mr.get("estimate"), "ci": mr.get("ci"), "trust_tier": tier,
               "diagnostics_available": sorted(diag.keys())}
    if main_key is None:
        summary["look_here_instead"] = [k for k in ("bounds_no_instrument", "instrument", "sensitivity") if k in diag]
    print(json.dumps(_finite(summary), indent=1, default=_json))
    if main_failed:
        sys.exit(3)


# ----------------------------------------------------------------------------
def cmd_figures(a):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    r = json.loads(Path(a.results).read_text())
    outdir = Path(a.outdir); outdir.mkdir(parents=True, exist_ok=True)
    main = r["main_method"]
    rows = [(k, v) for k, v in r["estimates"].items() if isinstance(v, dict) and v.get("estimate") is not None]
    rows.sort(key=lambda kv: (kv[0] != main, kv[0] == "naive_difference"))
    no_answer = main is None
    names = {"aipw_gbm": "Doubly robust ML", "aipw_spline": "Doubly robust, spline", "regression_linear": "Linear regression", "regression_gbm": "ML regression",
             "ipw_gbm": "Propensity weighting", "double_ml": "Double ML (overlap-weighted)", "causal_forest": "Causal forest", "naive_difference": "Raw gap (not adjusted)",
             "causalpfn": "CausalPFN (foundation model)", "aipw_tabpfn": "Doubly robust, TabPFN"}
    fig, ax = plt.subplots(figsize=(7, 0.45 * len(rows) + 1.2))
    for i, (k, v) in enumerate(rows):
        yv = len(rows) - i
        col = "#1f5fa6" if k == main else ("#b5542c" if k == "naive_difference" else "#6b6b6b")
        ax.plot(v["estimate"], yv, "o", color=col, ms=7 if k == main else 5)
        if v.get("ci"):
            ax.plot(v["ci"], [yv, yv], "-", color=col, lw=2 if k == main else 1)
        lab = names.get(k, k.replace("_", " "))
        if k == main and "main" not in lab:
            lab += " (main)"
        ax.text(ax.get_xlim()[0], yv, "", va="center")
        ax.annotate(lab, (0, yv), xycoords=("axes fraction", "data"), xytext=(-8, 0), textcoords="offset points", ha="right", va="center", fontsize=9)
    ax.axvline(0, color="#999", lw=0.8)
    ax.set_yticks([]); ax.set_xlabel("Estimated effect (dot) and 95% range (bar)")
    if no_answer:
        ax.set_title(f"Tier {r.get('trust_tier')}: no answer. Adjusted estimates below are biased reference points only", fontsize=9, loc="left", color="#b5542c")
        b = r.get("diagnostics", {}).get("bounds_no_instrument", {}).get("mtr_mts") or r.get("diagnostics", {}).get("instrument", {}).get("bounds_on_average_effect")
        if isinstance(b, dict) and b.get("lower") is not None:
            ax.axvspan(b["lower"], b["upper"], color="#1f5fa6", alpha=0.12, label="range the true effect lies in (under stated assumptions)")
            ax.legend(loc="upper center", bbox_to_anchor=(0.4, -0.12), fontsize=8, frameon=False)
    else:
        ax.set_title("Main result and sensitivity checks", fontsize=10, loc="left")
    fig.subplots_adjust(left=0.38)
    p = outdir / "methods.png"; fig.savefig(p, dpi=150, bbox_inches="tight"); print(f"wrote {p}")
    if r.get("dag"):
        import ca_dag
        ca_dag.draw(r["dag"], outdir / "dag.png"); (outdir / "dag.mmd").write_text(ca_dag.mermaid(r["dag"]))
        print(f"wrote {outdir / 'dag.png'}")


def cmd_codebook(a):
    df = core.load_data(a.data)
    dump(checks.codebook_draft(df, a.treatment, a.outcome), a.out)


def cmd_report(a):
    import ca_report
    ca_report.main(a.results, a.narrative, a.out)


def cmd_power(a):
    r = core.power_two_groups(a.baseline, a.lift, a.sd, a.alpha, a.power, a.ratio)
    print(json.dumps(r, indent=1))
    if a.results:
        res = json.loads(Path(a.results).read_text())
        pw = [p for p in res.setdefault("diagnostics", {}).get("power", []) if p.get("lift") != r["lift"]]
        res["diagnostics"]["power"] = sorted(pw + [r], key=lambda p: p["lift"])
        dump(res, a.results)
    if a.out:
        dump(r, a.out)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("profile"); p.add_argument("--data", required=True); p.add_argument("--treatment"); p.add_argument("--outcome"); p.add_argument("--out", default="profile.json"); p.set_defaults(f=cmd_profile)
    p = sub.add_parser("identify"); p.add_argument("spec"); p.add_argument("--out", default="identification.json"); p.set_defaults(f=cmd_identify)
    p = sub.add_parser("dag"); p.add_argument("spec"); p.add_argument("--outdir", default="."); p.set_defaults(f=cmd_dag)
    p = sub.add_parser("run"); p.add_argument("spec"); p.add_argument("--out", default="results.json"); p.set_defaults(f=cmd_run)
    p = sub.add_parser("figures"); p.add_argument("results"); p.add_argument("--outdir", default="."); p.set_defaults(f=cmd_figures)
    p = sub.add_parser("codebook"); p.add_argument("--data", required=True); p.add_argument("--treatment"); p.add_argument("--outcome"); p.add_argument("--out", default="codebook.json"); p.set_defaults(f=cmd_codebook)
    p = sub.add_parser("report"); p.add_argument("results"); p.add_argument("--narrative"); p.add_argument("--out", default="report.html"); p.set_defaults(f=cmd_report)
    p = sub.add_parser("power"); p.add_argument("--lift", type=float, required=True); p.add_argument("--baseline", type=float); p.add_argument("--sd", type=float)
    p.add_argument("--alpha", type=float, default=0.05); p.add_argument("--power", type=float, default=0.8); p.add_argument("--ratio", type=float, default=1.0); p.add_argument("--out"); p.add_argument("--results", help="also store the result in results.json for the report"); p.set_defaults(f=cmd_power)
    a = ap.parse_args(); a.f(a)


if __name__ == "__main__":
    main()
