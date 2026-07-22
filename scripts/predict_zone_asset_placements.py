"""Inspect relation-placement predictions for zone-attached assets."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import torch

from export_zone_asset_placement_dataset import export_scene
from train_zone_asset_placement_mlp import ZoneAssetPlacementMLP, row_features


ROOT = Path(__file__).resolve().parents[1]


def build_feature_vector(features: dict[str, float], feature_names: list[str]) -> torch.Tensor:
    return torch.tensor([[features.get(name, 0.0) for name in feature_names]], dtype=torch.float32)


def load_model(model_path: Path) -> tuple[ZoneAssetPlacementMLP, dict[str, Any]]:
    checkpoint = torch.load(model_path, map_location="cpu")
    model = ZoneAssetPlacementMLP(len(checkpoint["feature_names"]))
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    return model, checkpoint


def yaw_from_sincos(sin_value: float, cos_value: float) -> float:
    return math.degrees(math.atan2(sin_value, cos_value))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene", type=Path, help="Compiled Unity scene JSON to inspect.")
    parser.add_argument(
        "--model",
        type=Path,
        default=ROOT / "models" / "zone_asset_placement_mlp_accessory" / "zone_asset_placement_mlp.pt",
    )
    parser.add_argument("--source-kind", choices=["all", "accessory", "rule_scatter"], default="accessory")
    parser.add_argument("--limit", type=int, default=12)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model, checkpoint = load_model(args.model)
    feature_names = checkpoint["feature_names"]
    x_mean = checkpoint["x_mean"]
    x_std = checkpoint["x_std"]
    y_mean = checkpoint["y_mean"]
    y_std = checkpoint["y_std"]

    rows = export_scene(args.scene.resolve())
    if args.source_kind != "all":
        rows = [row for row in rows if row["input"]["asset"].get("source_kind") == args.source_kind]

    predictions = []
    for row in rows[: args.limit]:
        features = row_features(row)
        x = build_feature_vector(features, feature_names)
        x = (x - x_mean) / x_std
        with torch.no_grad():
            pred = model(x).squeeze(0)
        pred = pred * y_std + y_mean
        target = row["target"]
        rel = target["relative_position"]
        pred_x = float(pred[0])
        pred_z = float(pred[1])
        pred_yaw = yaw_from_sincos(float(pred[2]), float(pred[3]))
        target_yaw = float(target["relative_yaw"])
        position_error = math.hypot(pred_x - float(rel["x"]), pred_z - float(rel["z"]))
        yaw_error = abs((pred_yaw - target_yaw + 180.0) % 360.0 - 180.0)
        predictions.append(
            {
                "zone_id": row["zone_id"],
                "dependent_id": row["dependent_id"],
                "facility_type": row["input"]["zone"]["facility_type"],
                "asset": row["input"]["asset"]["prefab_name"],
                "source_kind": row["input"]["asset"]["source_kind"],
                "target": {
                    "relative_x": round(float(rel["x"]), 3),
                    "relative_z": round(float(rel["z"]), 3),
                    "relative_yaw": round(target_yaw, 2),
                },
                "prediction": {
                    "relative_x": round(pred_x, 3),
                    "relative_z": round(pred_z, 3),
                    "relative_yaw": round(pred_yaw, 2),
                },
                "error": {
                    "position_m": round(position_error, 3),
                    "yaw_deg": round(yaw_error, 2),
                },
            }
        )

    print(json.dumps(predictions, indent=2))


if __name__ == "__main__":
    main()
