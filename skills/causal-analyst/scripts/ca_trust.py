"""Trust grade (A to D) and the reasons behind it, from the estimates and diagnostics.

Every cap is listed in references/results.md; keep the two in step.
"""
from __future__ import annotations

import math

import numpy as np


def trust_tier(ident, res, diag, main_key, spec):
    reasons = []
    if not ident.get("identifiable"):
        return "D", ["The question cannot be answered from this data without assumptions it cannot support; see bounds / complier effect."]
    main = res.get(main_key, {}) or {}
    est = main.get("estimate")
    if est is None or "error" in main or not math.isfinite(est):
        return "D", [f"The main method ({main_key}) failed: {str(main.get('error', 'no estimate'))[:200]}. No answer can be given from this run."]
    tier = "A" if spec.get("randomized") else "B"
    if ident.get("strategy") == "front-door":
        tier = "C"
        reasons.append("The answer uses the front-door route: it rests on the whole effect passing through the middle step, and on the hidden driver not touching that step. Neither can be checked from the data.")
    elif tier == "B":
        reasons.append("Observational data: rests on no important unrecorded factor (cannot be checked).")
    small = spec.get("_small_group")
    if small:
        tier = "C" if tier in ("A", "B") else tier
        reasons.append(f"Only {small} rows in the smaller group; estimates this small are fragile.")
    ov = diag.get("overlap", {})
    if ov and (ov.get("share_below_0.05", 0) + ov.get("share_above_0.95", 0)) > 0.05:
        tier = "C" if tier in ("A", "B") else tier
        reasons.append(f"Weak overlap: {100*(ov['share_below_0.05']+ov['share_above_0.95']):.1f}% of units are almost always or never treated; part of the answer is extrapolated.")
    if diag.get("max_abs_smd_after", 0) > 0.1:
        reasons.append(f"Some imbalance remains after weighting (max SMD {diag['max_abs_smd_after']:.2f}); the doubly robust main method compensates, but treat with care.")
    pl = diag.get("placebo_permuted_treatment")
    if pl and not pl["passes"]:
        tier = "C" if tier in ("A", "B") else tier
        reasons.append("Shuffled-action check failed: giving the action to random rows still showed an effect. That points to a data or software problem, not a real effect.")
    sens = diag.get("sensitivity", {})
    if sens.get("strongest_measured") and tier != "A":
        rv = sens["robustness_value"]
        strongest = sens["strongest_measured"]["strength"]
        excludes_zero = bool(main.get("ci")) and not (main["ci"][0] <= 0 <= main["ci"][1])
        if excludes_zero and rv < 0.5 * strongest and tier == "B":
            tier = "C"
            reasons.append(f"A hidden factor half as strong as '{sens['strongest_measured']['confounder']}' could erase the effect: grade capped at C.")
        elif rv < strongest:
            reasons.append(f"A hidden factor about as strong as '{sens['strongest_measured']['confounder']}' (already controlled) could erase the effect (robustness value {rv:.2f} vs {strongest:.2f}). This is a caution, not proof of bias.")
    # Disagreement in standard-error units, among methods that target the same quantity.
    same_target = ("regression_linear", "aipw_spline", "ipw_gbm", "causal_forest", "aipw_gbm")
    se_main = (main["ci"][1] - main["ci"][0]) / 3.92 if main.get("ci") else None
    far = []
    if se_main:
        for k in same_target:
            v = res.get(k) or {}
            if k == main_key or v.get("estimate") is None or not v.get("ci") or "error" in v:
                continue
            se_k = (v["ci"][1] - v["ci"][0]) / 3.92
            if abs(v["estimate"] - est) > 2.5 * math.sqrt(se_k ** 2 + se_main ** 2):
                far.append((k, v["estimate"]))
    if main_key == "front_door":
        adj = [(k, (res.get(k) or {}).get("estimate")) for k in same_target if (res.get(k) or {}).get("estimate") is not None]
        if adj:
            reasons.append("The adjustment methods give " + ", ".join(f"{k} {e_:.3g}" for k, e_ in adj[:3])
                           + f". They assume no hidden driver, which is exactly what the front-door route does not assume; the gap to {est:.3g} is roughly the bias the hidden driver would cause.")
    elif len(far) >= 2:
        tier = "C" if tier in ("A", "B") else tier
        reasons.append("Methods disagree beyond sampling noise: " + ", ".join(f"{k} {e_:.3g}" for k, e_ in far) + f" vs main {est:.3g}. The answer depends on modelling choices.")
    for fm, fname in (("causalpfn", "CausalPFN"), ("aipw_tabpfn", "TabPFN")):
        fr = res.get(fm, {})
        if main.get("ci") and fr.get("estimate") is not None and not (main["ci"][0] <= fr["estimate"] <= main["ci"][1]):
            reasons.append(f"The {fname} foundation-model cross-check ({fr['estimate']:.3g}) falls outside the main 95% range; treat the size of the effect with extra care, especially where overlap is weak.")
    cb = diag.get("codebook") or {}
    if cb.get("no_meaning") or cb.get("unconfirmed"):
        cols = (cb.get("no_meaning") or []) + (cb.get("unconfirmed") or [])
        reasons.append(f"The meaning of {len(cols)} column(s) used was assumed, not confirmed by you: {', '.join(cols[:8])}{' and more' if len(cols) > 8 else ''}. A misread column can put the diagram, and the answer, wrong.")
    if not spec.get("randomized") and not spec.get("outcome_baseline"):
        reasons.append("No before-the-action measure of the outcome was named, so if past results drove who got the action (reverse causation), the estimate may be off.")
    alt = diag.get("alternatives") or {}
    if main.get("ci") and est is not None:
        lo_, hi_ = main["ci"]
        movers = [a for a in alt.get("user", []) if a.get("estimate") is not None and not a.get("illustrative") and not (lo_ <= a["estimate"] <= hi_)]
        if movers:
            flips = [a for a in movers if a["estimate"] * est < 0]
            if flips and tier in ("A", "B"):
                tier = "C"
            reasons.append("Under an alternative diagram the answer moves outside the main range: " + "; ".join(f"{a['name']} gives {a['estimate']:.3g}" for a in movers[:3]) + ". The result depends on which diagram is right.")
    sc = diag.get("structure_check") or {}
    dismissed = spec.get("dismissed_findings", {})
    cons = [f_["column"] for f_ in sc.get("findings", []) if f_["kind"] == "possible consequence" and f_["column"] not in dismissed]
    if cons:
        reasons.append(f"The data pattern suggests {', '.join(cons)} may be influenced by the action or the outcome (collider-like). Confirm timing; if so, it should not be a control.")
    sim = diag.get("simulation_check") or {}
    if sim.get("reps"):
        run_se = float(np.mean([(r_["ci"][1] - r_["ci"][0]) / 3.92 for r_ in sim["runs"]]))
        off_se = abs(sim["bias"]) / (run_se / math.sqrt(sim["reps"])) if run_se else 0
        if (sim["reps"] >= 3 and sim["coverage"] < 0.5) or off_se > 3:
            tier = "C" if tier in ("A", "B") else tier
            reasons.append(f"On your data with a planted effect of {sim['planted']:.3g}, the main method recovered {sim['mean_estimate']:.3g} ({sim['coverage']:.0%} of ranges contained it). It struggles with this data's structure.")
    ncs = [x for x in (diag.get("negative_controls") or []) if "estimate" in x and not x.get("passes")]
    if ncs:
        tier = "C" if tier in ("A", "B") else tier
        reasons.append("The action shows an 'effect' on something it cannot plausibly change: " + "; ".join(f"{x['column']} {x['estimate']:+.3g}" for x in ncs)
                       + ". That points to an unrecorded difference between the groups, which likely also inflates the main answer.")
    iv = ((diag.get("instrument") or {}).get("complier_effect_2sls") or {})
    # Credit the random nudge only if it is precise enough to tell a biased answer from a right one.
    iv_agrees = False
    if iv.get("ci") and main.get("ci"):
        se_iv = (iv["ci"][1] - iv["ci"][0]) / 3.92
        se_d = math.sqrt(se_iv ** 2 + se_main ** 2)
        iv_agrees = abs(iv["estimate"] - est) <= 1.96 * se_d and 2 * 1.96 * se_d < abs(est)
    if iv_agrees and spec.get("suspected_hidden"):
        reasons.append(f"The random nudge gives an independent estimate ({iv['estimate']:.3g}) that agrees with the main one, which argues against a strong hidden driver.")
    for sh in spec.get("suspected_hidden", []) if not spec.get("randomized") else []:
        lbl = sh.get("label") if isinstance(sh, dict) else str(sh)
        if not iv_agrees:
            tier = "C" if tier in ("A", "B") else tier
        reasons.append(f"Domain knowledge suggests an unrecorded driver: {lbl}. It is not in the data; see how strong it would need to be.")
    pz = diag.get("plausibility")
    if pz and not pz["inside"]:
        if pz["far_outside"]:
            tier = "C" if tier in ("A", "B") else tier
        reasons.append(f"The estimate ({pz['estimate']:.3g}) is {'far ' if pz['far_outside'] else ''}outside the range expected before the run ({pz['low']:.3g} to {pz['high']:.3g}; {pz['basis'] or pz['source']}). Either this setting differs or something is missing from the diagram.")
    if main.get("ci") and est is not None and main["ci"][0] <= 0 <= main["ci"][1]:
        reasons.append("The 95% range includes zero: the data are consistent with no effect.")
    return tier, reasons
