"""Inspect zone asset predictions from the trained zone asset MLP."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import torch

from export_zone_asset_dataset import export_scene
from train_zone_asset_mlp import ZoneAssetMLP, row_features


ROOT = Path(__file__).resolve().parents[1]


def build_feature_vector(features: dict[str, float], feature_names: list[str]) -> torch.Tensor:
    return torch.tensor([[features.get(name, 0.0) for name in feature_names]], dtype=torch.float32)


def load_model(model_path: Path) -> tuple[ZoneAssetMLP, dict[str, Any]]:
    checkpoint = torch.load(model_path, map_location="cpu")
    model = ZoneAssetMLP(len(checkpoint["feature_names"]), len(checkpoint["label_names"]))
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    return model, checkpoint


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene", type=Path, help="Compiled Unity scene JSON to inspect.")
    parser.add_argument(
        "--model",
        type=Path,
        default=ROOT / "models" / "zone_asset_mlp" / "zone_asset_mlp.pt",
    )
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--limit", type=int, default=8)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model, checkpoint = load_model(args.model)
    feature_names = checkpoint["feature_names"]
    label_names = checkpoint["label_names"]
    mean = checkpoint["mean"]
    std = checkpoint["std"]

    rows = export_scene(args.scene.resolve())
    predictions = []
    for row in rows[: args.limit]:
        features = row_features(row)
        x = build_feature_vector(features, feature_names)
        x = (x - mean) / std
        with torch.no_grad():
            probs = torch.sigmoid(model(x)).squeeze(0)
        top = probs.topk(min(args.top_k, len(label_names)))
        predictions.append(
            {
                "zone_id": row["zone_id"],
                "facility_type": row["input"]["zone"]["facility_type"],
                "category": row["input"]["zone"].get("category"),
                "target_assets": row["target"]["asset_names"],
                "predicted_assets": [
                    {"asset": label_names[index], "probability": round(float(prob), 4)}
                    for prob, index in zip(top.values, top.indices)
                ],
            }
        )

    print(json.dumps(predictions, indent=2))


if __name__ == "__main__":
    main()
