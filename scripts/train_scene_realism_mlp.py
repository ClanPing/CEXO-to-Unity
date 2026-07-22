"""Train a small PyTorch MLP to predict whether a scene needs review.

The model consumes scene-level records from export_ml_dataset.py and predicts
whether Unity-scene validation will pass or require review. This is the first
actual neural baseline in the pipeline; it is deliberately compact so it can
be retrained often as the scene compiler changes.
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
    if isinstance(value, bool):
        out[prefix] = 1.0 if value else 0.0
    elif isinstance(value, (int, float)):
        out[prefix] = float(value)
    elif isinstance(value, dict):
        for key, child in value.items():
            flatten_numeric(f"{prefix}.{key}" if prefix else str(key), child, out)


def row_features(row: dict[str, Any]) -> dict[str, float]:
    data = row["input"]
    features: dict[str, float] = {}
    flatten_numeric("object_count", data.get("object_count"), features)
    flatten_numeric("generation_seed", data.get("generation_seed"), features)
    flatten_numeric("site", data.get("site", {}), features)
    flatten_numeric("geometry", data.get("geometry", {}), features)
    for label, count in data.get("object_count_by_label", {}).items():
        features[f"object_count_by_label.{label}"] = float(count)
    for key, value in data.get("scatter_summary", {}).items():
        flatten_numeric(f"scatter_summary.{key}", value, features)
    return features


def layout_id(row: dict[str, Any]) -> str:
    return str(row["input"]["site"].get("source_layout_id") or row.get("scene_id"))


def split_rows(rows: list[dict[str, Any]], test_fraction: float, seed: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    layout_ids = sorted({layout_id(row) for row in rows})
    rng = random.Random(seed)
    rng.shuffle(layout_ids)
    test_count = max(1, round(len(layout_ids) * test_fraction)) if len(layout_ids) > 1 else 0
    test_ids = set(layout_ids[:test_count])
    train = [row for row in rows if layout_id(row) not in test_ids]
    test = [row for row in rows if layout_id(row) in test_ids]
    return train, test


def build_matrix(
    rows: list[dict[str, Any]],
    feature_names: list[str] | None = None,
) -> tuple[torch.Tensor, torch.Tensor, list[str]]:
    row_dicts = [row_features(row) for row in rows]
    if feature_names is None:
        feature_names = sorted({key for features in row_dicts for key in features})
    matrix = []
    labels = []
    for row, features in zip(rows, row_dicts):
        matrix.append([features.get(name, 0.0) for name in feature_names])
        labels.append(0.0 if row["target"].get("is_training_clean") else 1.0)
    return torch.tensor(matrix, dtype=torch.float32), torch.tensor(labels, dtype=torch.float32).unsqueeze(1), feature_names


def standardize(train_x: torch.Tensor, test_x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    mean = train_x.mean(dim=0, keepdim=True)
    std = train_x.std(dim=0, keepdim=True)
    std = torch.where(std < 1e-6, torch.ones_like(std), std)
    return (train_x - mean) / std, (test_x - mean) / std, mean.squeeze(0), std.squeeze(0)


class SceneRealismMLP(nn.Module):
    def __init__(self, input_dim: int) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, 64),
            nn.ReLU(),
            nn.Dropout(0.10),
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


def binary_metrics(logits: torch.Tensor, labels: torch.Tensor) -> dict[str, float]:
    probs = torch.sigmoid(logits).detach().cpu()
    y = labels.detach().cpu()
    pred = (probs >= 0.5).float()
    tp = float(((pred == 1) & (y == 1)).sum())
    tn = float(((pred == 0) & (y == 0)).sum())
    fp = float(((pred == 1) & (y == 0)).sum())
    fn = float(((pred == 0) & (y == 1)).sum())
    total = max(1.0, tp + tn + fp + fn)
    precision = tp / max(1.0, tp + fp)
    recall = tp / max(1.0, tp + fn)
    return {
        "accuracy": (tp + tn) / total,
        "precision_needs_review": precision,
        "recall_needs_review": recall,
        "f1_needs_review": 2 * precision * recall / max(1e-6, precision + recall),
        "positive_rate_predicted": float(pred.mean()),
        "positive_rate_actual": float(y.mean()),
        "count": int(total),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=ROOT / "output" / "first_ml_iteration_safe_filtered" / "ml_dataset")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "models" / "scene_realism_mlp")
    parser.add_argument("--epochs", type=int, default=120)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--test-fraction", type=float, default=0.25)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    rows = read_jsonl(args.dataset_dir / "scene_realism.jsonl")
    train_rows, test_rows = split_rows(rows, args.test_fraction, args.seed)
    train_x, train_y, feature_names = build_matrix(train_rows)
    test_x, test_y, _ = build_matrix(test_rows, feature_names)
    train_x, test_x, mean, std = standardize(train_x, test_x)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    train_x = train_x.to(device)
    train_y = train_y.to(device)
    test_x = test_x.to(device)
    test_y = test_y.to(device)

    model = SceneRealismMLP(train_x.shape[1]).to(device)
    positive = float(train_y.sum().item())
    negative = float(train_y.numel() - positive)
    pos_weight = torch.tensor([negative / max(1.0, positive)], dtype=torch.float32, device=device)
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
                    "train": binary_metrics(train_logits, train_y),
                    "test": binary_metrics(test_logits, test_y),
                }
            )

    model.eval()
    with torch.no_grad():
        train_logits = model(train_x)
        test_logits = model(test_x)
    metrics = {
        "task": "scene_realism_needs_review_binary_classification",
        "device": str(device),
        "feature_count": len(feature_names),
        "train": binary_metrics(train_logits, train_y),
        "test": binary_metrics(test_logits, test_y),
        "history": history,
        "split": {
            "train_records": len(train_rows),
            "test_records": len(test_rows),
            "test_fraction": args.test_fraction,
        },
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "model_state_dict": model.state_dict(),
            "feature_names": feature_names,
            "mean": mean.cpu(),
            "std": std.cpu(),
            "metrics": metrics,
        },
        args.output_dir / "scene_realism_mlp.pt",
    )
    with (args.output_dir / "feature_spec.json").open("w", encoding="utf-8") as file:
        json.dump({"feature_names": feature_names}, file, indent=2)
    with (args.output_dir / "metrics.json").open("w", encoding="utf-8") as file:
        json.dump(metrics, file, indent=2)

    print(f"Wrote scene realism MLP to {args.output_dir}")
    print(f"Device: {device}")
    print(f"Test metrics: {json.dumps(metrics['test'], indent=2)}")


if __name__ == "__main__":
    main()
