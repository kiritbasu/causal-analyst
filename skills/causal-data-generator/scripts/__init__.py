"""causal-data-generator as an importable package (`import causal_data_generator`).

The scripts in this folder still run on their own; see ../SKILL.md. Generate with
``causal_data_generator.cg_engine.generate``; load the ready-made scenarios with ``scenario``.
"""

from __future__ import annotations

import json
from pathlib import Path

__version__ = "0.4.0"

_HERE = Path(__file__).resolve().parent
# Installed wheel: scenarios/ sits inside the package. Source tree: next to scripts/.
SCENARIO_DIR = _HERE / "scenarios" if (_HERE / "scenarios").is_dir() else _HERE.parent / "scenarios"


def scenario_ids() -> list[str]:
    """Ids of the ready-made scenarios, sorted."""
    return sorted(p.stem for p in SCENARIO_DIR.glob("*.json"))


def scenario(scenario_id: str) -> dict:
    """One ready-made scenario, as the dict ``cg_engine.generate`` takes."""
    if scenario_id not in scenario_ids():
        raise KeyError(f"no ready-made scenario {scenario_id!r}; have {scenario_ids()}")
    return json.loads((SCENARIO_DIR / f"{scenario_id}.json").read_text())
