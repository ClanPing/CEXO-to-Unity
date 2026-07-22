"""Train simple baselines on exported construction scene ML records.

These baselines are intentionally small and dependency-free. They establish
what the dataset can predict before we introduce PyTorch or a deeper model.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def split_by_scene(rows: list[dict[str, Any]], test_fraction: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    scene_ids = sorted({row.get("scene_id") for row in rows})
    test_count = max(1, round(len(scene_ids) * test_fraction)) if len(scene_ids) > 1 else 0
    test_scenes = set(scene_ids[-test_count:])
    train_rows = [row for row in rows if row.get("scene_id") not in test_scenes]
    test_rows = [row for row in rows if row.get("scene_id") in test_scenes]
    return train_rows, test_rows


def asset_key(row: dict[str, Any]) -> str:
    data = row["input"]
    return "|".join(
        [
            str(data.get("source_kind")),
            str(data.get("facility_type")),
            str(data.get("category")),
        ]
    )


def train_asset_baseline(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    global_counts: Counter[str] = Counter()
    for row in rows:
        target = row["target"].get("prefab_name")
        if not target:
            continue
        counts[asset_key(row)][target] += 1
        global_counts[target] += 1

    return {
        "model_type": "most_common_prefab_by_source_kind_facility_category",
        "global_default": global_counts.most_common(1)[0][0] if global_counts else None,
        "table": {
            key: {
                "prediction": counter.most_common(1)[0][0],
                "counts": dict(counter),
            }
            for key, counter in sorted(counts.items())
        },
    }


def predict_asset(model: dict[str, Any], row: dict[str, Any]) -> str | None:
    key = asset_key(row)
    if key in model["table"]:
        return model["table"][key]["prediction"]
    return model.get("global_default")


def evaluate_asset(model: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"accuracy": None, "count": 0}
    correct = 0
    for row in rows:
        correct += int(predict_asset(model, row) == row["target"].get("prefab_name"))
    return {"accuracy": correct / len(rows), "count": len(rows)}


def relation_key(row: dict[str, Any]) -> str:
    data = row["input"]
    return "|".join(
        [
            str(data.get("dependent_label")),
            str(data.get("anchor_label")),
            str(data.get("relation_source")),
        ]
    )


def train_relation_baseline(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    global_rows = []
    for row in rows:
        grouped[relation_key(row)].append(row)
        global_rows.append(row)

    def stats(group: list[dict[str, Any]]) -> dict[str, float]:
        return {
            "relative_x": mean(row["target"]["relative_position"]["x"] for row in group),
            "relative_z": mean(row["target"]["relative_position"]["z"] for row in group),
            "relative_yaw": mean(row["target"]["relative_yaw"] for row in group),
            "distance_xz": mean(row["target"]["distance_xz"] for row in group),
            "count": len(group),
        }

    return {
        "model_type": "mean_relative_pose_by_dependent_anchor_relation",
        "global_default": stats(global_rows) if global_rows else None,
        "table": {key: stats(group) for key, group in sorted(grouped.items())},
    }


def predict_relation(model: dict[str, Any], row: dict[str, Any]) -> dict[str, float] | None:
    key = relation_key(row)
    return model["table"].get(key, model.get("global_default"))


def evaluate_relation(model: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"mean_abs_relative_x_error": None, "mean_abs_relative_z_error": None, "mean_abs_yaw_error": None, "count": 0}

    x_errors = []
    z_errors = []
    yaw_errors = []
    for row in rows:
        pred = predict_relation(model, row)
        if pred is None:
            continue
        target = row["target"]
        x_errors.append(abs(pred["relative_x"] - target["relative_position"]["x"]))
        z_errors.append(abs(pred["relative_z"] - target["relative_position"]["z"]))
        yaw_errors.append(abs(pred["relative_yaw"] - target["relative_yaw"]))

    return {
        "mean_abs_relative_x_error": mean(x_errors) if x_errors else None,
        "mean_abs_relative_z_error": mean(z_errors) if z_errors else None,
        "mean_abs_yaw_error": mean(yaw_errors) if yaw_errors else None,
        "count": len(rows),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=ROOT / "output" / "ml_dataset",
        help="Directory produced by export_ml_dataset.py.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "output" / "ml_baselines",
        help="Directory for trained baseline JSON files and metrics.",
    )
    parser.add_argument("--test-fraction", type=float, default=0.25)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asset_rows = read_jsonl(args.dataset_dir / "asset_selection.jsonl")
    relation_rows = read_jsonl(args.dataset_dir / "relation_placement.jsonl")

    asset_train, asset_test = split_by_scene(asset_rows, args.test_fraction)
    relation_train, relation_test = split_by_scene(relation_rows, args.test_fraction)

    asset_model = train_asset_baseline(asset_train)
    relation_model = train_relation_baseline(relation_train)

    metrics = {
        "asset_selection": {
            "train": evaluate_asset(asset_model, asset_train),
            "test": evaluate_asset(asset_model, asset_test),
        },
        "relation_placement": {
            "train": evaluate_relation(relation_model, relation_train),
            "test": evaluate_relation(relation_model, relation_test),
        },
        "split": {
            "asset_train_records": len(asset_train),
            "asset_test_records": len(asset_test),
            "relation_train_records": len(relation_train),
            "relation_test_records": len(relation_test),
            "test_fraction": args.test_fraction,
        },
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / "asset_selection_baseline.json").open("w", encoding="utf-8") as file:
        json.dump(asset_model, file, indent=2)
    with (args.output_dir / "relation_placement_baseline.json").open("w", encoding="utf-8") as file:
        json.dump(relation_model, file, indent=2)
    with (args.output_dir / "metrics.json").open("w", encoding="utf-8") as file:
        json.dump(metrics, file, indent=2)

    print(f"Wrote baselines to {args.output_dir}")
    print(f"Asset test accuracy: {metrics['asset_selection']['test']['accuracy']}")
    print(
        "Relation test MAE x/z/yaw: "
        f"{metrics['relation_placement']['test']['mean_abs_relative_x_error']}, "
        f"{metrics['relation_placement']['test']['mean_abs_relative_z_error']}, "
        f"{metrics['relation_placement']['test']['mean_abs_yaw_error']}"
    )


if __name__ == "__main__":
    main()
