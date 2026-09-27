"""The skill's instructions must not contain the eval cases: no eval column names, no answers.
Otherwise a passing eval could just mean the model read the answer in the skill."""
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "causal-analyst"
GENERIC = {"id", "account_id", "adherent", "industry", "language", "month", "role", "period", "week", "store", "age", "region", "tenure_months", "income_k", "urban", "segment", "t", "y", "x", "treated", "outcome"}


def _skill_text():
    parts = [p.read_text() for p in SKILL.rglob("*.md")]
    parts += [p.read_text() for p in (SKILL / "scripts").glob("*.py")]
    return "\n".join(parts).lower()


def _eval_columns():
    cols = set()
    for ev in json.loads((ROOT / "evals" / "evals.json").read_text())["evals"]:
        for f in ev.get("files", []):
            p = ROOT / f
            if p.suffix == ".csv" and p.exists():
                cols |= {c.lower() for c in pd.read_csv(p, nrows=1).columns}
    return {c for c in cols if c not in GENERIC and len(c) > 3}


def test_no_eval_columns_in_skill():
    text = _skill_text()
    leaked = sorted(c for c in _eval_columns() if re.search(rf"\b{re.escape(c)}\b", text))
    assert not leaked, f"eval column names appear in the skill: {leaked}"


def test_no_eval_answers_in_skill():
    text = _skill_text()
    for ev in json.loads((ROOT / "evals" / "evals.json").read_text())["evals"]:
        truth = ev.get("true_answer")
        # only distinctive answers (3+ significant digits); small round numbers appear everywhere
        if isinstance(truth, (int, float)) and len(f"{abs(truth):g}".replace(".", "").lstrip("0")) >= 3:
            assert f"{truth:g}" not in text, f"eval {ev['id']} answer {truth:g} appears in the skill"
