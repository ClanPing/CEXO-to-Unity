"""Train a relation-aware placement model for selected zone assets."""

from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from typing import Any

import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset


ROOT = Path(__file__).resolve().parents[1]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def flatten_numeric(prefix: str, value: Any, out: dict[str, float]) -> None:
    if value is None:
        return
    if isinstance(value, bool):
        out[prefix] = 1.0 if value else 0.0
    elif isinstance(value, (int, float)):
        out[prefix] = float(value)
    elif isinstance(value, dict):
        for key, child in value.items():
            flatten_numeric(f"{prefix}.{key}" if prefix else str(key), child, out)


def one_hot(prefix: str, value: Any, out: dict[str, float]) -> None:
    if value is not None:
        out[f"{prefix}.{value}"] = 1.0


def row_features(row: dict[str, Any]) -> dict[str, float]:
    data = row["input"]
    features: dict[str, float] = {}
    one_hot("zone.facility_type", data["zone"].get("facility_type"), features)
    one_hot("zone.category", data["zone"].get("category"), features)
    one_hot("asset.prefab_name", data["asset"].get("prefab_name"), features)
    one_hot("asset.construction_class", data["asset"].get("construction_class"), features)
    one_hot("asset.source_kind", data["asset"].get("source_kind"), features)
    one_hot("asset.accessory_type", data["asset"].get("accessory_type"), features)
    flatten_numeric("zone", data.get("zone", {}), features)
    flatten_numeric("asset", data.get("asset", {}), features)
    flatten_numeric("site", data.get("site", {}), features)
    flatten_numeric("context", data.get("context", {}), features)
    return features


def target_vector(row: dict[str, Any]) -> list[float]:
    target = row["target"]
    rel = target["relative_position"]
    return [
        float(rel["x"]),
        float(rel["z"]),
        float(target["relative_yaw_sin"]),
        float(target["relative_yaw_cos"]),
    ]


def layout_id(row: dict[str, Any]) -> str:
    return str(row.get("source_layout_id") or row.get("scene_id"))


def split_rows(rows: list[dict[str, Any]], test_fraction: float, seed: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    layout_ids = sorted({layout_id(row) for row in rows})
    rng = random.Random(seed)
    rng.shuffle(layout_ids)
    test_count = max(1, round(len(layout_ids) * test_fraction)) if len(layout_ids) > 1 else 0
    test_ids = set(layout_ids[:test_count])
    return (
        [row for row in rows if layout_id(row) not in test_ids],
        [row for row in rows if layout_id(row) in test_ids],
    )


def build_matrix(
    rows: list[dict[str, Any]],
    feature_names: list[str] | None = None,
) -> tuple[torch.Tensor, torch.Tensor, list[str]]:
    feature_dicts = [row_features(row) for row in rows]
    if feature_names is None:
        feature_names = sorted({name for features in feature_dicts for name in features})
    x_rows = [[features.get(name, 0.0) for name in feature_names] for features in feature_dicts]
    y_rows = [target_vector(row) for row in rows]
    return torch.tensor(x_rows, dtype=torch.float32), torch.tensor(y_rows, dtype=torch.float32), feature_names


def standardize(train_x: torch.Tensor, test_x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    mean = train_x.mean(dim=0, keepdim=True)
    std = train_x.std(dim=0, keepdim=True)
    std = torch.where(std < 1e-6, torch.ones_like(std), std)
    return (train_x - mean) / std, (test_x - mean) / std, mean.squeeze(0), std.squeeze(0)


class ZoneAssetPlacementMLP(nn.Module):
    def __init__(self, input_dim: int) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, 160),
            nn.ReLU(),
            nn.Dropout(0.10),
            nn.Linear(160, 96),
            nn.ReLU(),
            nn.Dropout(0.06),
            nn.Linear(96, 4),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


def inverse_standardize(y: torch.Tensor, mean: torch.Tensor, std: torch.Tensor) -> torch.Tensor:
    return y * std.to(y.device) + mean.to(y.device)


def angle_degrees_from_sincos(values: torch.Tensor) -> torch.Tensor:
    return torch.rad2deg(torch.atan2(values[:, 2], values[:, 3]))


def angle_error_degrees(pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    pred_angle = angle_degrees_from_sincos(pred)
    target_angle = angle_degrees_from_sincos(target)
    return torch.abs((pred_angle - target_angle + 180.0) % 360.0 - 180.0)


def regression_metrics(pred: torch.Tensor, target: torch.Tensor) -> dict[str, float]:
    pred = pred.detach().cpu()
    target = target.detach().cpu()
    distance_error = torch.sqrt((pred[:, 0] - target[:, 0]) ** 2 + (pred[:, 1] - target[:, 1]) ** 2)
    return {
        "mae_relative_x_m": float(torch.mean(torch.abs(pred[:, 0] - target[:, 0]))),
        "mae_relative_z_m": float(torch.mean(torch.abs(pred[:, 1] - target[:, 1]))),
        "mean_position_error_m": float(torch.mean(distance_error)),
        "median_position_error_m": float(torch.median(distance_error)),
        "mae_yaw_deg": float(torch.mean(angle_error_degrees(pred, target))),
        "count": int(target.shape[0]),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=ROOT / "output" / "first_ml_iteration_safe_filtered" / "zone_asset_placement_dataset",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "models" / "zone_asset_placement_mlp",
    )
    parser.add_argument("--epochs", type=int, default=70)
    parser.add_argument("--batch-size", type=int, default=1024)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--test-fraction", type=float, default=0.25)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--source-kind",
        choices=["all", "accessory", "rule_scatter"],
        default="all",
        help="Train on all records or only one dependent source kind.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    random.seed(args.seed)
    torch.manual_seed(args.seed)

    rows = read_jsonl(args.dataset_dir / "zone_asset_placement_records.jsonl")
    if args.source_kind != "all":
        rows = [row for row in rows if row["input"]["asset"].get("source_kind") == args.source_kind]
    if not rows:
        raise SystemExit(f"No records found for source kind '{args.source_kind}'.")
    train_rows, test_rows = split_rows(rows, args.test_fraction, args.seed)
    train_x, train_y, feature_names = build_matrix(train_rows)
    test_x, test_y, _ = build_matrix(test_rows, feature_names)
    train_x, test_x, x_mean, x_std = standardize(train_x, test_x)
    train_y_scaled, test_y_scaled, y_mean, y_std = standardize(train_y, test_y)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    train_x = train_x.to(device)
    train_y_scaled = train_y_scaled.to(device)
    test_x = test_x.to(device)
    test_y_scaled = test_y_scaled.to(device)
    train_y = train_y.to(device)
    test_y = test_y.to(device)
    y_mean = y_mean.to(device)
    y_std = y_std.to(device)

    model = ZoneAssetPlacementMLP(train_x.shape[1]).to(device)
    criterion = nn.SmoothL1Loss(beta=0.5)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    loader = DataLoader(TensorDataset(train_x, train_y_scaled), batch_size=args.batch_size, shuffle=True)

    history = []
    for epoch in range(1, args.epochs + 1):
        model.train()
        losses = []
        for batch_x, batch_y in loader:
            optimizer.zero_grad()
            pred = model(batch_x)
            loss = criterion(pred, batch_y)
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        if epoch == 1 or epoch % 10 == 0 or epoch == args.epochs:
            model.eval()
            with torch.no_grad():
                train_pred = inverse_standardize(model(train_x), y_mean, y_std)
                test_pred = inverse_standardize(model(test_x), y_mean, y_std)
            history.append(
                {
                    "epoch": epoch,
                    "loss": sum(losses) / max(1, len(losses)),
                    "train": regression_metrics(train_pred, train_y),
                    "test": regression_metrics(test_pred, test_y),
                }
            )

    model.eval()
    with torch.no_grad():
        train_pred = inverse_standardize(model(train_x), y_mean, y_std)
        test_pred = inverse_standardize(model(test_x), y_mean, y_std)

    metrics = {
        "task": "zone_asset_relation_placement_regression",
        "device": str(device),
        "feature_count": len(feature_names),
        "source_kind_filter": args.source_kind,
        "train": regression_metrics(train_pred, train_y),
        "test": regression_metrics(test_pred, test_y),
        "split": {
            "train_records": len(train_rows),
            "test_records": len(test_rows),
            "test_fraction": args.test_fraction,
        },
        "history": history,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "model_state_dict": model.state_dict(),
            "feature_names": feature_names,
            "x_mean": x_mean.cpu(),
            "x_std": x_std.cpu(),
            "y_mean": y_mean.cpu(),
            "y_std": y_std.cpu(),
            "metrics": metrics,
        },
        args.output_dir / "zone_asset_placement_mlp.pt",
    )
    with (args.output_dir / "feature_spec.json").open("w", encoding="utf-8") as file:
        json.dump({"feature_names": feature_names}, file, indent=2)
    with (args.output_dir / "metrics.json").open("w", encoding="utf-8") as file:
        json.dump(metrics, file, indent=2)

    print(f"Wrote zone asset placement MLP to {args.output_dir}")
    print(f"Device: {device}")
    print(f"Test metrics: {json.dumps(metrics['test'], indent=2)}")


if __name__ == "__main__":
    main()
