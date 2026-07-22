"""Train a zone-context multi-label asset-selection model.

Input: optimized layout zone specification plus nearby-zone context.
Target: set of assets/prefabs that should be attached to that zone.
"""

from __future__ import annotations

import argparse
import json
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
    flatten_numeric("zone", data.get("zone", {}), features)
    flatten_numeric("site", data.get("site", {}), features)
    flatten_numeric("context", data.get("context", {}), features)
    return features


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


def build_label_names(rows: list[dict[str, Any]], min_count: int) -> list[str]:
    counts: dict[str, int] = {}
    for row in rows:
        for label in row["target"].get("asset_names", []):
            counts[label] = counts.get(label, 0) + 1
    return sorted(label for label, count in counts.items() if count >= min_count)


def build_matrix(
    rows: list[dict[str, Any]],
    feature_names: list[str] | None = None,
    label_names: list[str] | None = None,
    min_label_count: int = 10,
) -> tuple[torch.Tensor, torch.Tensor, list[str], list[str]]:
    feature_dicts = [row_features(row) for row in rows]
    if feature_names is None:
        feature_names = sorted({name for features in feature_dicts for name in features})
    if label_names is None:
        label_names = build_label_names(rows, min_label_count)
    label_to_index = {label: index for index, label in enumerate(label_names)}

    x_rows = []
    y_rows = []
    for row, features in zip(rows, feature_dicts):
        x_rows.append([features.get(name, 0.0) for name in feature_names])
        y = [0.0] * len(label_names)
        for label in row["target"].get("asset_names", []):
            if label in label_to_index:
                y[label_to_index[label]] = 1.0
        y_rows.append(y)

    return (
        torch.tensor(x_rows, dtype=torch.float32),
        torch.tensor(y_rows, dtype=torch.float32),
        feature_names,
        label_names,
    )


def standardize(train_x: torch.Tensor, test_x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    mean = train_x.mean(dim=0, keepdim=True)
    std = train_x.std(dim=0, keepdim=True)
    std = torch.where(std < 1e-6, torch.ones_like(std), std)
    return (train_x - mean) / std, (test_x - mean) / std, mean.squeeze(0), std.squeeze(0)


class ZoneAssetMLP(nn.Module):
    def __init__(self, input_dim: int, output_dim: int) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, 128),
            nn.ReLU(),
            nn.Dropout(0.12),
            nn.Linear(128, 96),
            nn.ReLU(),
            nn.Dropout(0.08),
            nn.Linear(96, output_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


def multilabel_metrics(logits: torch.Tensor, labels: torch.Tensor, top_k: int = 8) -> dict[str, float]:
    probs = torch.sigmoid(logits).detach().cpu()
    y = labels.detach().cpu()
    pred = (probs >= 0.5).float()
    tp = float(((pred == 1) & (y == 1)).sum())
    fp = float(((pred == 1) & (y == 0)).sum())
    fn = float(((pred == 0) & (y == 1)).sum())
    precision = tp / max(1.0, tp + fp)
    recall = tp / max(1.0, tp + fn)

    k = min(top_k, probs.shape[1])
    top_indices = probs.topk(k, dim=1).indices
    top_hits = []
    for row_index in range(probs.shape[0]):
        true = set(torch.where(y[row_index] > 0.5)[0].tolist())
        pred_top = set(top_indices[row_index].tolist())
        top_hits.append(len(true & pred_top) / max(1, len(true)))

    exact_match = float((pred == y).all(dim=1).float().mean())
    return {
        "micro_precision": precision,
        "micro_recall": recall,
        "micro_f1": 2 * precision * recall / max(1e-6, precision + recall),
        "top_k_recall": sum(top_hits) / max(1, len(top_hits)),
        "exact_match": exact_match,
        "average_true_labels": float(y.sum(dim=1).mean()),
        "average_predicted_labels": float(pred.sum(dim=1).mean()),
        "count": int(y.shape[0]),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=ROOT / "output" / "first_ml_iteration_safe_filtered" / "zone_asset_dataset",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "models" / "zone_asset_mlp",
    )
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--test-fraction", type=float, default=0.25)
    parser.add_argument("--min-label-count", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    random.seed(args.seed)
    torch.manual_seed(args.seed)

    rows = read_jsonl(args.dataset_dir / "zone_asset_records.jsonl")
    train_rows, test_rows = split_rows(rows, args.test_fraction, args.seed)
    train_x, train_y, feature_names, label_names = build_matrix(
        train_rows,
        min_label_count=args.min_label_count,
    )
    test_x, test_y, _, _ = build_matrix(test_rows, feature_names, label_names, args.min_label_count)
    train_x, test_x, mean, std = standardize(train_x, test_x)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    train_x = train_x.to(device)
    train_y = train_y.to(device)
    test_x = test_x.to(device)
    test_y = test_y.to(device)

    model = ZoneAssetMLP(train_x.shape[1], train_y.shape[1]).to(device)
    positives = train_y.sum(dim=0)
    negatives = train_y.shape[0] - positives
    pos_weight = torch.clamp(negatives / torch.clamp(positives, min=1.0), max=40.0).to(device)
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    loader = DataLoader(TensorDataset(train_x, train_y), batch_size=args.batch_size, shuffle=True)

    history = []
    for epoch in range(1, args.epochs + 1):
        model.train()
        losses = []
        for batch_x, batch_y in loader:
            optimizer.zero_grad()
            logits = model(batch_x)
            loss = criterion(logits, batch_y)
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        if epoch == 1 or epoch % 10 == 0 or epoch == args.epochs:
            model.eval()
            with torch.no_grad():
                train_logits = model(train_x)
                test_logits = model(test_x)
            history.append(
                {
                    "epoch": epoch,
                    "loss": sum(losses) / max(1, len(losses)),
                    "train": multilabel_metrics(train_logits, train_y),
                    "test": multilabel_metrics(test_logits, test_y),
                }
            )

    model.eval()
    with torch.no_grad():
        train_logits = model(train_x)
        test_logits = model(test_x)
    metrics = {
        "task": "zone_context_asset_set_prediction",
        "device": str(device),
        "feature_count": len(feature_names),
        "label_count": len(label_names),
        "train": multilabel_metrics(train_logits, train_y),
        "test": multilabel_metrics(test_logits, test_y),
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
            "label_names": label_names,
            "mean": mean.cpu(),
            "std": std.cpu(),
            "metrics": metrics,
        },
        args.output_dir / "zone_asset_mlp.pt",
    )
    with (args.output_dir / "feature_label_spec.json").open("w", encoding="utf-8") as file:
        json.dump({"feature_names": feature_names, "label_names": label_names}, file, indent=2)
    with (args.output_dir / "metrics.json").open("w", encoding="utf-8") as file:
        json.dump(metrics, file, indent=2)

    print(f"Wrote zone asset MLP to {args.output_dir}")
    print(f"Device: {device}")
    print(f"Labels: {len(label_names)}")
    print(f"Test metrics: {json.dumps(metrics['test'], indent=2)}")


if __name__ == "__main__":
    main()
