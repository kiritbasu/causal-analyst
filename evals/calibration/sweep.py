#!/usr/bin/env python3
"""Does the grade mean something? Generate datasets with a known answer, run the analyst's scripts with
the correct diagram (an 'oracle' plan, so this tests the grading, not the interview), and compare the
grade with the actual error.

    python evals/calibration/sweep.py --out evals/calibration/results [--seeds 2] [--n 4000]

Writes runs.csv (one row per dataset) and summary.md (error and coverage by grade).
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "causal-data-generator" / "scripts"))
import cg_engine as E  # noqa: E402

CA = ROOT / "skills" / "causal-analyst" / "scripts" / "ca.py"


def oracle_spec(scn, level, key, data, columns):
    s = E.resolve(scn, level)
    ren = key.get("column_names", {})
    conf = [ren.get(c, c) for c in key.get("correct_adjustment", [])]
    active = [h for h in s["hidden"] if h.get("to_treat") and h.get("to_outcome")]
    # A proxied hidden driver is what a careful analyst would adjust for via its stand-in; only an
    # unproxied one is declared as a named hidden driver.
    hidden = [h for h in active if not any(h["name"] in v.get("from_hidden", {}) for v in s["variables"])]
    spec = {"data": data, "treatment": ren.get(scn["treatment"]["name"], scn["treatment"]["name"]),
            "outcome": ren.get(scn["outcome"]["name"], scn["outcome"]["name"]), "confounders": conf,
            "estimand": scn.get("estimand", "ATE"), "budget": "quick", "seed": 1, "causalpfn_max_rows": 0,
            "hidden_confounding": "named_driver" if hidden else "none_known",
            "codebook": {c: {"meaning": c, "confirmed": True} for c in conf}}
    if hidden:
        spec["hidden_driver_note"] = hidden[0].get("label", hidden[0]["name"])
    if s.get("instrument") and ren.get(s["instrument"]["name"], s["instrument"]["name"]) in columns:
        spec["instruments"] = [ren.get(s["instrument"]["name"], s["instrument"]["name"])]
    return spec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).parent / "results"))
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--n", type=int, default=4000)
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    rows = []
    for f in sorted((ROOT / "skills" / "causal-data-generator" / "scenarios").glob("*.json")):
        scn = json.loads(f.read_text())
        if scn["design"] != "cross_section" or scn["treatment"].get("type", "binary") != "binary":
            continue
        for level in scn.get("levels", E.LEVELS):
            for seed in range(1, a.seeds + 1):
                d = out / f"{scn['id']}-{level}-{seed}"
                d.mkdir(exist_ok=True)
                if (d / "row.json").exists():   # resume
                    rows.append(json.loads((d / "row.json").read_text()))
                    continue
                df, _, key = E.generate(scn, level, None, seed, a.n)
                df.to_csv(d / "data.csv", index=False)
                spec = oracle_spec(scn, level, key, str(d / "data.csv"), list(df.columns))
                (d / "spec.json").write_text(json.dumps(spec, indent=1))
                p = subprocess.run([sys.executable, str(CA), "run", str(d / "spec.json"), "--out", str(d / "results.json")], capture_output=True, text=True)
                truth = key["true_value_primary"]
                row = {"scenario": scn["id"], "level": level, "seed": seed, "truth": truth, "exit": p.returncode}
                if p.returncode == 0:
                    r = json.loads((d / "results.json").read_text())
                    m = r.get("main_result") or {}
                    row.update(tier=r["trust_tier"], estimate=m.get("estimate"))
                    if m.get("ci"):
                        lo, hi = m["ci"]
                        se = (hi - lo) / 3.92
                        row.update(covers=lo <= truth <= hi, error_in_se=abs(m["estimate"] - truth) / se if se else None,
                                   rel_error=abs(m["estimate"] - truth) / abs(truth) if truth else None)
                rows.append(row)
                (d / "row.json").write_text(json.dumps(row))
                print(json.dumps(row), flush=True)
    t = pd.DataFrame(rows)
    t.to_csv(out / "runs.csv", index=False)
    g = t.groupby("tier").agg(runs=("scenario", "size"), covers=("covers", "mean"),
                              median_error_in_se=("error_in_se", "median"), median_rel_error=("rel_error", "median"))
    (out / "summary.md").write_text("# Grade vs actual error (oracle plans)\n\n" + g.to_markdown(floatfmt=".2f") +
                                    "\n\nA grade is well calibrated when A/B runs cover the truth about 95% of the time and C/D runs often don't.\n")
    print(g)


if __name__ == "__main__":
    main()
