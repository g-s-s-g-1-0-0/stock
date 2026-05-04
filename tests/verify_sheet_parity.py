"""Compare saved sheet samples with the Python rule engine.

Replace data/sheet_parity_samples.json with exported Google Sheet examples to
turn this from a smoke check into an exact sheet parity gate.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from calculator.rules import evaluate_buy_condition, indicator_from_mapping


def main() -> None:
    samples_path = ROOT / "data" / "sheet_parity_samples.json"
    samples = json.loads(samples_path.read_text(encoding="utf-8"))
    failures: list[str] = []

    for sample in samples:
        values = sample["input"]
        expected = sample["expected"]
        result = evaluate_buy_condition(
            indicator_from_mapping(values),
            vix=values.get("vix"),
            ixic_dist=values.get("ixicDist"),
            ixic_filter_active=bool(values.get("ixicFilterActive")),
        )
        for key, expected_value in expected.items():
            actual_value = result.get(key)
            if actual_value != expected_value:
                failures.append(
                    f"{sample['name']}: {key} expected {expected_value!r}, got {actual_value!r}"
                )

    if failures:
        raise AssertionError("\n".join(failures))
    print(f"sheet parity samples passed: {len(samples)}")


if __name__ == "__main__":
    main()
