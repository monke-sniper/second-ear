"""Builds eval/results/table.md from every results file that exists.

In: the `second-ear/results-v1` JSON files in eval/results. Out: one Markdown table per
file and system, in the columns of docs/SPEC.md §8: test, metric, value, n, notes.
It computes nothing: every number is copied from a results file, with its n.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eval.metrics import RESULTS_SCHEMA

TABLE_NAME = "table.md"
COLUMNS = ("test", "metric", "value", "n", "notes")
# Files in reading order; any other results file follows by name.
ORDER = ("model.json", "baselines.json", "heldout.json", "calls.json")


def load_results(results_dir: Path) -> list[tuple[str, dict[str, Any]]]:
    """Every results-v1 file with rows, as (file name, payload), in reading order."""
    found = []
    for path in sorted(Path(results_dir).glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(payload, dict) and payload.get("schema") == RESULTS_SCHEMA and payload.get("rows"):
            found.append((path.name, payload))
    return sorted(found, key=lambda item: (ORDER.index(item[0]) if item[0] in ORDER else len(ORDER), item[0]))


def _cell(value: Any) -> str:
    if value is None:
        return "n/a"
    return str(value).replace("|", "\\|").replace("\n", " ")


def _section(name: str, system: str, payload: dict[str, Any], rows: list[dict]) -> list[str]:
    lines = [f"## {system} ({name}, {payload.get('created_utc', 'no date')})", ""]
    scorer = payload.get("scorer") or {}
    if scorer.get("is_stand_in") and system == scorer.get("name"):
        lines += ["Scorer: the keyword stand-in, not a trained model.", ""]
    lines += ["| " + " | ".join(COLUMNS) + " |", "|" + "---|" * len(COLUMNS)]
    lines += ["| " + " | ".join(_cell(row.get(column)) for column in COLUMNS) + " |" for row in rows]
    return lines + [""]


def table_markdown(results_dir: Path) -> str:
    """The whole table. A file with rows from two systems gets one section for each."""
    results = load_results(results_dir)
    lines = [
        "# Results",
        "",
        "Built by `python -m eval.run_eval` from: " + (", ".join(f"`{name}`" for name, _ in results) or "nothing yet") + ".",
        "Every number is copied from its results file. `n` is that metric's own denominator.",
        "",
    ]
    for name, payload in results:
        systems: dict[str, list[dict]] = {}
        for row in payload["rows"]:
            systems.setdefault(str(row.get("system") or payload.get("system") or "unknown"), []).append(row)
        for system, rows in systems.items():
            lines += _section(name, system, payload, rows)
    return "\n".join(lines).rstrip() + "\n"


def write_table(results_dir: Path) -> Path:
    """Write table.md next to the results files and return its path."""
    target = Path(results_dir) / TABLE_NAME
    target.write_text(table_markdown(results_dir), encoding="utf-8")
    return target
