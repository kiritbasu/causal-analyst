#!/usr/bin/env python3
"""causal-data-generator CLI.

  python cg.py list                                   ready-made use cases, by industry
  python cg.py plan <id|scenario.json> [--level L] [--dials '{"missing":0.1}'] [--n N]
                                                      one-screen plan to confirm (no data written)
  python cg.py generate <id|scenario.json> --out DIR [--level L] [--seed S] [--n N] [--dials JSON]
                                                      writes DIR/data.csv + DIR/brief.md (share these)
                                                      and DIR-key/answer_key.json + generate.py + scenario.json (sealed)
  python cg.py set <id|scenario.json> --out DIR --seeds 5 [--level L] ...
                                                      several seeds of the same scenario (DIR/seed-42, ...)
  python cg.py check <scenario.json>                  validate a custom scenario file

Levels: starter | realistic | tricky | unanswerable. Dials override the level's realism settings:
nonlinear (0-1), heavy_tails, overlap ("good"|"weak"), missing (0-0.3), measurement_error (0-0.3),
irrelevant (extra columns), misleading_names, zero_effect, missing_pattern ("random"|"depends_on_action").
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cg_engine as E  # noqa: E402

LIB = HERE.parent / "scenarios"


def load(ref: str) -> dict:
    p = Path(ref)
    if p.suffix == ".json" and p.exists():
        return json.loads(p.read_text())
    f = LIB / f"{ref}.json"
    if not f.exists():
        ids = sorted(x.stem for x in LIB.glob("*.json"))
        sys.exit(f"Unknown scenario '{ref}'. Ready-made: {', '.join(ids)}")
    return json.loads(f.read_text())


def cmd_list(a):
    rows = []
    for f in sorted(LIB.glob("*.json")):
        s = json.loads(f.read_text())
        rows.append((s.get("industry", ""), s["id"], s.get("title", ""), s.get("design", ""), s.get("teaser", ""), s.get("default_level", "realistic")))
    if a.json:
        keys = ["industry", "id", "title", "design", "default_level"] if a.blind else ["industry", "id", "title", "design", "teaser", "default_level"]
        print(json.dumps([{k: v for k, v in zip(["industry", "id", "title", "design", "teaser", "default_level"], r) if k in keys} for r in rows], indent=1))
        return
    cur = None
    for ind, i, t, d, teaser, lvl in sorted(rows):
        if ind != cur:
            print(f"\n{ind}")
            cur = ind
        # Teasers name the trap, so blind mode shows titles only.
        print(f"  {i:<28} {t}  [{d}]" + ("" if a.blind else f"  {teaser}"))


DESIGN_WORDS = {"cross_section": "one row per {unit}; a one-off action", "cutoff": "one row per {unit}; the action depends on a score passing a cutoff",
                "rollout": "one row per {unit} per period; the change rolls out at different times"}


def plan_text(s0: dict, level: str, dials: dict, n: int | None, blind: bool = False) -> str:
    s = E.resolve(s0, level, dials)
    ren = E._names(s) if s["dials"]["misleading_names"] else {}
    nm = lambda c: f"{c} (appears as '{ren[c]}')" if c in ren else c
    n = n or s["n"]
    tr, y = s["treatment"], s["outcome"]
    lines = [f"PLAN · {s['title']}  (level: {level})", "",
             f"Question   {s['question']}",
             f"Design     " + DESIGN_WORDS[s["design"]].format(unit=s.get("unit", "row")) + (f", {s['rollout']['periods']} periods" if s["design"] == "rollout" else ""),
             f"Rows       {n:,} {s.get('units', 'rows')}" + (f" × {s['rollout']['periods']} periods" if s["design"] == "rollout" else ""),
             f"Action     {nm(tr['name'])}: {tr.get('meaning', tr.get('label'))}",
             f"Outcome    {nm(y['name'])}: {y.get('meaning', y.get('label'))}", ""]
    if blind:
        lines += ["Blind plan: the true effect and the traps are kept for the answer key.", "",
                  "Brief (what the expert tells the analyst):"] + [f"  • {nt['text']}" for nt in s["notes"]]
        lines += ["", "You'll get: data.csv + brief.md (to share), and a separate answer key + generate.py (sealed)."]
        return "\n".join(lines)
    eff = s.get("effect", {})
    if tr.get("type") == "dose":
        lines.append(f"True effect   {'curved, diminishing returns' if eff.get('shape') == 'curved' else 'straight line'} (exact values go in the answer key)")
    else:
        lines.append(f"True effect   set to {eff.get('ate')} {eff.get('unit_label', '')} on average" + (" (zero-effect test)" if s["dials"]["zero_effect"] else "") + "; the exact realised value goes in the answer key")
    lines += ["", "What's in the data (the traps):"]
    story = []
    if any(v.get("to_treat") for v in s["variables"]):
        story.append("Things we recorded drive both who gets the action and the outcome.")
    for v in s["variables"]:
        if v.get("role") == "prior_outcome":
            story.append(f"Past results ({nm(v['name'])}) steer who gets the action.")
    for h in s["hidden"]:
        if h.get("to_treat") and h.get("to_outcome"):
            px = [v["name"] for v in s["variables"] if h["name"] in v.get("from_hidden", {})]
            story.append(f"Something not recorded ({h.get('label', h['name'])}) drives both" + (f"; {', '.join(px)} partly {'tracks' if len(px) == 1 else 'track'} it." if px else "; nothing recorded stands in for it."))
    if s.get("instrument"):
        story.append(f"A random nudge ({s['instrument']['name']}) changed who got the action.")
    if s.get("mediator"):
        story.append(f"The effect flows partly through a middle step we can see ({nm(s['mediator']['name'])}).")
    for p in s["post_treatment"]:
        story.append(f"{nm(p['name'])} is " + ("a consequence of the action" if p.get("kind") != "collider" else "caused by both the action and the outcome") + " — a column that must not be controlled for.")
    if s.get("heterogeneity"):
        story.append(f"It helps some groups more than others ({s['heterogeneity'].get('label')}).")
    if s.get("negative_control"):
        story.append(f"{s['negative_control']['name']} can't be changed by the action (a built-in check).")
    if s["design"] == "cutoff":
        story.append(f"The action switches on at {s['cutoff'].get('label', s['cutoff']['running'])} = {s['cutoff']['threshold']}" + (" (partly: a fuzzy cutoff)" if s["cutoff"].get("fuzzy") else "") + ".")
    if s["design"] == "rollout":
        ro = s["rollout"]
        story.append(f"Adoption in {len(ro.get('cohorts', [1]))} wave(s); {int(100 * ro.get('never_share', .3))}% never adopt." + (" Effects build up over time." if ro.get("ramp_periods") else "") + (" Adopters were already on a different path (breaks parallel trends)." if ro.get("trend_selection") else ""))
    lines += [f"  • {x}" for x in story]
    d = s["dials"]
    real = []
    if d["nonlinear"]:
        real.append("curved relationships")
    if d["heavy_tails"]:
        real.append("occasional extreme values")
    ro = s["design"] == "rollout"
    if d["overlap"] == "weak" and not ro and s["design"] != "cutoff":
        real.append("weak overlap (some units almost always / never get the action)")
    if d["missing"]:
        real.append(f"{int(round(100 * d['missing']))}% missing values" + (", more often for rows without the action" if d.get("missing_pattern") == "depends_on_action" else ""))
    if d["measurement_error"] and any(v.get("noisy") for v in s["variables"]):
        real.append("noisy measurement of a key driver")
    if d["irrelevant"]:
        real.append(f"{d['irrelevant']} irrelevant columns")
    if d["misleading_names"] and any(v.get("cryptic") for grp in ("variables", "post_treatment") for v in s.get(grp, [])) or \
            (d["misleading_names"] and any((s.get(k) or {}).get("cryptic") for k in ("treatment", "outcome", "mediator", "instrument", "negative_control"))):
        real.append("cryptic column names")
    lines += ["", "Realism: " + (", ".join(real) if real else "clean data")]
    lines += ["", "Brief (what the expert tells the analyst):"] + [f"  • {nt['text']}" for nt in s["notes"]]
    lines += ["", "You'll get: data.csv + brief.md (to share), and a separate answer key + generate.py (sealed)."]
    return "\n".join(lines)


def write_bundle(scn, level, dials, seed, n, out: Path, kdir: Path | None = None):
    df, brief, key = E.generate(scn, level, dials, seed, n)
    out.mkdir(parents=True, exist_ok=True)
    kdir = kdir or out.parent / (out.name + "-key")
    if kdir.resolve() == out.resolve() or out.resolve() in kdir.resolve().parents:
        sys.exit("The answer key can't go inside the data folder: anyone given the data would see it. Choose another --key-dir.")
    kdir.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "data.csv", index=False)
    (out / "brief.md").write_text(brief)
    (kdir / "answer_key.json").write_text(json.dumps(key, indent=1))
    (kdir / "scenario.json").write_text(json.dumps(scn, indent=1))
    (kdir / "generate.py").write_text(export_script(scn, level, dials, seed, n))
    return df, key, kdir


def export_script(scn, level, dials, seed, n):
    src = (HERE / "cg_engine.py").read_text()
    return (f'#!/usr/bin/env python3\n"""Regenerate this dataset exactly: python generate.py [--out DIR]\n'
            f'Scenario {scn["id"]}, level {level}, seed {seed}. Requires numpy, pandas, scipy, statsmodels.\n'
            f'Edit SCENARIO / LEVEL / DIALS / SEED below to make variants."""\n'
            + src.split('"""', 2)[2] +
            "\n\n# ---------------------------------------------------------------------------- this dataset\n"
            f"SCENARIO = json.loads({json.dumps(scn, indent=1)!r})\nLEVEL = {level!r}\nDIALS = json.loads({json.dumps(dials or {})!r})\nSEED = {int(seed)}\nN = {n!r}\n\n"
            "if __name__ == '__main__':\n"
            "    import argparse, pathlib\n"
            "    ap = argparse.ArgumentParser(); ap.add_argument('--out', default='.'); a = ap.parse_args()\n"
            "    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)\n"
            "    df, brief, key = generate(SCENARIO, LEVEL, DIALS, SEED, N)\n"
            "    df.to_csv(out / 'data.csv', index=False); (out / 'brief.md').write_text(brief)\n"
            "    (out / 'answer_key.json').write_text(json.dumps(key, indent=1))\n"
            "    print(f\"wrote {len(df):,} rows, fingerprint {key['fingerprint']}\")\n")


def summary(df, key, blind=False):
    if blind:
        return {"rows": len(df), "columns": list(df.columns), "fingerprint": key["fingerprint"],
                "note": "Blind mode: truth, quick estimates and warnings are in the answer key only."}
    prim = next((t for t in key["targets"] if t.get("primary")), key["targets"][0])
    val = prim.get("value", key.get("true_value_primary"))
    out = {"rows": len(df), "columns": list(df.columns), "fingerprint": key["fingerprint"],
           "primary_target": prim["label"], "true_value": val,
           "quick_methods": [(m["method"], round(m["estimate"], 4), m["verdict"], m["expected"]) for m in key["methods"]]}
    warn = []
    for m in key["methods"]:
        if m["expected"] == "should fail" and m["verdict"] != "misses":
            warn.append(f"Trap may not bite on this draw: '{m['method']}' is {m['verdict']} ({m['off_by_pct']}% off). A larger n or a stronger setting makes it clearer.")
        if m["expected"] == "should work" and m["verdict"] == "misses":
            warn.append(f"'{m['method']}' misses by {m['off_by_pct']}% although it should work; check the scenario (sample size, overlap, curvature).")
    out["warnings"] = warn
    return out


def cmd_plan(a):
    print(plan_text(load(a.scenario), a.level or load(a.scenario).get("default_level", "realistic"), json.loads(a.dials or "{}"), a.n, a.blind))


def cmd_generate(a):
    scn = load(a.scenario)
    level = a.level or scn.get("default_level", "realistic")
    df, key, kdir = write_bundle(scn, level, json.loads(a.dials or "{}"), a.seed, a.n, Path(a.out), Path(a.key_dir) if a.key_dir else None)
    s = summary(df, key, a.blind)
    s.update(shared=str(Path(a.out)), sealed=str(kdir))
    print(json.dumps(s, indent=1, default=str))


def cmd_set(a):
    scn = load(a.scenario)
    level = a.level or scn.get("default_level", "realistic")
    base = Path(a.out)
    kbase = Path(a.key_dir) if a.key_dir else base.parent / (base.name + "-key")
    rows = []
    for i in range(a.seeds):
        seed = a.seed + i
        df, key, kdir = write_bundle(scn, level, json.loads(a.dials or "{}"), seed, a.n, base / f"seed-{seed}",
                                     kbase / f"seed-{seed}")
        prim = next((t for t in key["targets"] if t.get("primary")), key["targets"][0])
        rows.append({"seed": seed, "fingerprint": key["fingerprint"], "true_value": prim.get("value", key.get("true_value_primary")),
                     "plain_comparison": key["methods"][0]["estimate"]})
    kbase.mkdir(parents=True, exist_ok=True)
    (kbase / "set_summary.json").write_text(json.dumps(rows, indent=1))
    if a.blind:
        print(json.dumps({"datasets": [str(base / f"seed-{r['seed']}") for r in rows], "fingerprints": [r["fingerprint"] for r in rows],
                          "sealed": str(kbase), "note": "Blind mode: truth and quick estimates are in the sealed folder only."}, indent=1))
    else:
        print(json.dumps(rows, indent=1))


def cmd_check(a):
    scn = load(a.scenario)
    need = ["id", "title", "question", "design", "n", "treatment", "outcome"]
    miss = [k for k in need if k not in scn]
    if miss:
        sys.exit(f"missing fields: {miss}")
    if scn.get("mediator") and scn["outcome"].get("type", "continuous") != "continuous":
        sys.exit("A middle step (mediator) is only supported with a continuous outcome; use a continuous outcome (e.g. a rate) or drop the mediator.")
    if scn.get("design") == "cutoff" and scn.get("instrument"):
        sys.exit("A cutoff design can't also have an instrument.")
    for lvl in scn.get("levels", E.LEVELS):
        try:
            df, _, key = E.generate(scn, lvl, None, 1, int(scn["n"]))
            print(f"{lvl}: {len(df):,} rows; truth {key.get('true_value_primary', float('nan')):.4g}")
            for m in key["methods"]:
                flag = "  <-- check" if (m["expected"] == "should fail" and m["verdict"] != "misses") or (m["expected"] == "should work" and m["verdict"] == "misses") else ""
                print(f"    {m['method'][:70]:<70} {m['estimate']:>10.4g}  {m['verdict']:<14} ({m['expected']}){flag}")
        except Exception as ex:
            print(lvl, "FAILED:", ex)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list"); p.add_argument("--json", action="store_true")
    p.add_argument("--blind", action="store_true", help="titles only: the teasers hint at the traps"); p.set_defaults(f=cmd_list)
    for name, fn in (("plan", cmd_plan), ("generate", cmd_generate), ("set", cmd_set)):
        p = sub.add_parser(name); p.add_argument("scenario"); p.add_argument("--level", choices=E.LEVELS); p.add_argument("--dials")
        p.add_argument("--n", type=int); p.add_argument("--seed", type=int, default=42)
        p.add_argument("--blind", action="store_true", help="don't print the truth, traps or quick estimates (for blind tests)")
        if name != "plan":
            p.add_argument("--out", required=True)
            p.add_argument("--key-dir", help="where to put the sealed answer key (default: <out>-key next to the data); "
                                              "put it outside any folder an analyst will read")
        if name == "set":
            p.add_argument("--seeds", type=int, default=5)
        p.set_defaults(f=fn)
    p = sub.add_parser("check"); p.add_argument("scenario"); p.set_defaults(f=cmd_check)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
