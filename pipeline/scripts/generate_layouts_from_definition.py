#!/usr/bin/env python3
"""Generate raw construction layout JSONs from a Stage 1 problem definition.

This is a lightweight quality-diversity style generator used by the Stage 1 GUI.
It consumes ``stage1_problem_definition_v1`` JSON exported by the editor and
writes raw layout JSON files that the existing Stage 2 compiler already accepts.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FACILITY_LABELS_2D = {"core": "C", "crane": "CR", "storage": "S", "office": "OF", "rest_area": "RA"}
FACILITY_COLORS_2D = {
    "core": "#4e79a7",
    "crane": "#e15759",
    "storage": "#59a14f",
    "office": "#af7aa1",
    "rest_area": "#ff9d9a",
}


@dataclass
class Candidate:
    facilities: list[dict[str, Any]]
    entrances: list[dict[str, float]]
    objectives: dict[str, float]
    behaviors: dict[str, float]
    feasibility: dict[str, Any]
    score: float


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")


def normalize_polygon(definition: dict[str, Any]) -> list[list[float]]:
    polygon = definition.get("boundary_polygon") or []
    if polygon and isinstance(polygon[0], dict):
        return [[float(p["x"]), float(p["y"])] for p in polygon]

    world_polygon = definition.get("boundary_polygon_world_m") or []
    width = float(definition["site_width_m"])
    length = float(definition["site_length_m"])
    if world_polygon and isinstance(world_polygon[0], dict):
        return [[float(p["x_m"]) / width, float(p["y_m"]) / length] for p in world_polygon]
    return [[float(x), float(y)] for x, y in polygon]


def normalize_exclusion_zones(definition: dict[str, Any]) -> list[dict[str, Any]]:
    zones = []
    width = float(definition["site_width_m"])
    length = float(definition["site_length_m"])
    for index, zone in enumerate(definition.get("exclusion_zones", [])):
        polygon = zone.get("polygon", [])
        if polygon and isinstance(polygon[0], dict):
            if "x_m" in polygon[0]:
                points = [[float(p["x_m"]) / width, float(p["y_m"]) / length] for p in polygon]
            else:
                points = [[float(p["x"]), float(p["y"])] for p in polygon]
        else:
            points = [[float(x), float(y)] for x, y in polygon]
        zones.append({"name": zone.get("name", f"exclusion_{index:02d}"), "polygon": points})
    return zones


def normalize_entrances(definition: dict[str, Any]) -> list[dict[str, float]]:
    entrances = []
    width = float(definition["site_width_m"])
    length = float(definition["site_length_m"])
    for entrance in definition.get("entrances", []):
        if "x" in entrance and "y" in entrance:
            entrances.append({"x": float(entrance["x"]), "y": float(entrance["y"])})
        else:
            entrances.append({"x": float(entrance["x_m"]) / width, "y": float(entrance["y_m"]) / length})
    return entrances


def point_in_polygon(point: tuple[float, float], polygon: list[list[float]]) -> bool:
    x, y = point
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        intersects = (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi
        if intersects:
            inside = not inside
        j = i
    return inside


def polygon_bounds(polygon: list[list[float]]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    return min(xs), min(ys), max(xs), max(ys)


def generate_random_entrances(definition: dict[str, Any], polygon: list[list[float]], rng: random.Random) -> list[dict[str, float]]:
    optimisation = definition.get("optimisation", {})
    min_entrances = int(optimisation.get("min_entrances", 1))
    max_entrances = int(optimisation.get("max_entrances", max(min_entrances, 1)))
    count = rng.randint(min_entrances, max(max_entrances, min_entrances))
    if count <= 0 or len(polygon) < 2:
        return []

    edge_lengths = []
    for index, start in enumerate(polygon):
        end = polygon[(index + 1) % len(polygon)]
        edge_lengths.append((index, math.hypot(end[0] - start[0], end[1] - start[1])))
    total_length = sum(length for _, length in edge_lengths) or 1.0

    def choose_edge() -> int:
        target = rng.random() * total_length
        cursor = 0.0
        for index, length in edge_lengths:
            cursor += length
            if cursor >= target:
                return index
        return edge_lengths[-1][0]

    entrances: list[dict[str, float]] = []
    min_separation = 0.16
    for _ in range(count):
        placed = None
        for _attempt in range(80):
            edge = choose_edge()
            start = polygon[edge]
            end = polygon[(edge + 1) % len(polygon)]
            t = rng.uniform(0.12, 0.88)
            x = start[0] + (end[0] - start[0]) * t
            y = start[1] + (end[1] - start[1]) * t
            if any(math.hypot(x - item["x"], y - item["y"]) < min_separation for item in entrances):
                continue
            placed = {"x": x, "y": y}
            break
        if placed is None:
            edge = choose_edge()
            start = polygon[edge]
            end = polygon[(edge + 1) % len(polygon)]
            placed = {"x": (start[0] + end[0]) / 2, "y": (start[1] + end[1]) / 2}
        entrances.append(placed)
    return entrances


def rect_corners(facility: dict[str, Any]) -> list[tuple[float, float]]:
    half_w = float(facility["width"]) / 2.0
    half_l = float(facility["length"]) / 2.0
    x = float(facility["x"])
    y = float(facility["y"])
    return [(x - half_w, y - half_l), (x + half_w, y - half_l), (x + half_w, y + half_l), (x - half_w, y + half_l)]


def rects_overlap(a: dict[str, Any], b: dict[str, Any], padding: float = 0.006) -> bool:
    aw = float(a["width"]) / 2 + padding
    al = float(a["length"]) / 2 + padding
    bw = float(b["width"]) / 2 + padding
    bl = float(b["length"]) / 2 + padding
    return abs(float(a["x"]) - float(b["x"])) < (aw + bw) and abs(float(a["y"]) - float(b["y"])) < (al + bl)


def point_in_rect(point: tuple[float, float], facility: dict[str, Any]) -> bool:
    x, y = point
    half_w = float(facility["width"]) / 2.0
    half_l = float(facility["length"]) / 2.0
    return (
        float(facility["x"]) - half_w <= x <= float(facility["x"]) + half_w
        and float(facility["y"]) - half_l <= y <= float(facility["y"]) + half_l
    )


def orientation(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[1] - a[1]) * (c[0] - b[0]) - (b[0] - a[0]) * (c[1] - b[1])


def on_segment(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> bool:
    return min(a[0], c[0]) <= b[0] <= max(a[0], c[0]) and min(a[1], c[1]) <= b[1] <= max(a[1], c[1])


def segments_intersect(
    first_a: tuple[float, float],
    first_b: tuple[float, float],
    second_a: tuple[float, float],
    second_b: tuple[float, float],
) -> bool:
    o1 = orientation(first_a, first_b, second_a)
    o2 = orientation(first_a, first_b, second_b)
    o3 = orientation(second_a, second_b, first_a)
    o4 = orientation(second_a, second_b, first_b)
    eps = 1e-9
    if o1 * o2 < 0 and o3 * o4 < 0:
        return True
    if abs(o1) <= eps and on_segment(first_a, second_a, first_b):
        return True
    if abs(o2) <= eps and on_segment(first_a, second_b, first_b):
        return True
    if abs(o3) <= eps and on_segment(second_a, first_a, second_b):
        return True
    if abs(o4) <= eps and on_segment(second_a, first_b, second_b):
        return True
    return False


def rect_intersects_polygon(facility: dict[str, Any], polygon: list[list[float]]) -> bool:
    corners = rect_corners(facility)
    if any(point_in_polygon(corner, polygon) for corner in corners):
        return True
    if point_in_polygon((float(facility["x"]), float(facility["y"])), polygon):
        return True
    if any(point_in_rect((point[0], point[1]), facility) for point in polygon):
        return True
    rect_edges = list(zip(corners, corners[1:] + corners[:1]))
    poly_points = [(point[0], point[1]) for point in polygon]
    polygon_edges = list(zip(poly_points, poly_points[1:] + poly_points[:1]))
    return any(segments_intersect(a, b, c, d) for a, b in rect_edges for c, d in polygon_edges)


def intersects_exclusion_zones(facility: dict[str, Any], zones: list[dict[str, Any]]) -> bool:
    return any(rect_intersects_polygon(facility, zone.get("polygon", [])) for zone in zones if zone.get("polygon"))


def facility_inside_boundary(facility: dict[str, Any], polygon: list[list[float]]) -> bool:
    return all(point_in_polygon(corner, polygon) for corner in rect_corners(facility))


def facility_category(ftype: str) -> str:
    if ftype == "crane":
        return "equipment"
    if ftype in {"office", "rest_area"}:
        return "worker"
    return "operational"


def sample_point(rng: random.Random, polygon: list[list[float]], bias: str, entrances: list[dict[str, float]]) -> tuple[float, float]:
    min_x, min_y, max_x, max_y = polygon_bounds(polygon)
    for _ in range(300):
        if bias == "entrance" and entrances and rng.random() < 0.75:
            anchor = rng.choice(entrances)
            x = rng.gauss(anchor["x"], 0.12)
            y = rng.gauss(anchor["y"], 0.12)
        elif bias == "center":
            x = rng.gauss((min_x + max_x) / 2, (max_x - min_x) / 5)
            y = rng.gauss((min_y + max_y) / 2, (max_y - min_y) / 5)
        else:
            x = rng.uniform(min_x, max_x)
            y = rng.uniform(min_y, max_y)
        x = min(max(x, min_x), max_x)
        y = min(max(y, min_y), max_y)
        if point_in_polygon((x, y), polygon):
            return x, y
    return (min_x + max_x) / 2, (min_y + max_y) / 2


def build_facility_sequence(definition: dict[str, Any]) -> list[dict[str, Any]]:
    sequence = []
    width = float(definition["site_width_m"])
    length = float(definition["site_length_m"])
    for ftype, cfg in definition.get("facility_requirements", {}).items():
        quantity = int(cfg.get("quantity", 0))
        for _ in range(quantity):
            sequence.append(
                {
                    "type": ftype,
                    "width": float(cfg.get("width_m", 5.0)) / width,
                    "length": float(cfg.get("length_m", 5.0)) / length,
                    "height_m": float(cfg.get("height_m", 3.0)),
                    "clearance": float(cfg.get("clearance_radius_m", 0.0)) / ((width + length) / 2),
                    "clearance_radius_m": float(cfg.get("clearance_radius_m", 0.0)),
                    "danger_radius_m": float(cfg.get("danger_radius_m", cfg.get("clearance_radius_m", 0.0))),
                    "optimal_reach_m": float(cfg.get("optimal_reach_m", 0.0)),
                    "operating_radius_m": float(cfg.get("operating_radius_m", 0.0)),
                }
            )
    order = {"core": 0, "crane": 1, "office": 2, "rest_area": 3, "storage": 4}
    return sorted(sequence, key=lambda item: order.get(item["type"], 99))


def nearest_distance(point: tuple[float, float], facilities: list[dict[str, Any]], types: set[str] | None = None) -> float:
    selected = [f for f in facilities if types is None or f["type"] in types]
    if not selected:
        return 1.0
    return min(math.hypot(point[0] - f["x"], point[1] - f["y"]) for f in selected)


def score_candidate(
    facilities: list[dict[str, Any]],
    polygon: list[list[float]],
    entrances: list[dict[str, float]],
    exclusion_zones: list[dict[str, Any]],
    weights: dict[str, float],
) -> Candidate:
    violations = []
    overlap_count = 0
    outside_count = 0

    for idx, facility in enumerate(facilities):
        if not all(point_in_polygon(corner, polygon) for corner in rect_corners(facility)):
            outside_count += 1
            violations.append(f"{facility['type']}_{idx:02d}_outside_boundary")
        if intersects_exclusion_zones(facility, exclusion_zones):
            outside_count += 1
            violations.append(f"{facility['type']}_{idx:02d}_inside_road_or_exclusion_zone")
        for other in facilities[idx + 1 :]:
            if rects_overlap(facility, other):
                overlap_count += 1

    if overlap_count:
        violations.append(f"{overlap_count}_overlap_pairs")

    entrance_points = [(item["x"], item["y"]) for item in entrances]
    worker = [f for f in facilities if f["category"] == "worker"]
    operational = [f for f in facilities if f["category"] == "operational"]
    cranes = [f for f in facilities if f["type"] == "crane"]
    cores = [f for f in facilities if f["type"] == "core"]
    storages = [f for f in facilities if f["type"] == "storage"]

    entrance_clearance_penalty = 0.0
    for facility in facilities:
        for entrance in entrance_points:
            distance = math.hypot(facility["x"] - entrance[0], facility["y"] - entrance[1])
            entrance_clearance_penalty += max(0.0, 0.07 - distance) / 0.07

    safety = 1.0 - min(1.0, outside_count * 0.35 + overlap_count * 0.18 + entrance_clearance_penalty * 0.08)

    crane_core_score = 0.0
    if cranes and cores:
        crane_core_score = sum(max(0.0, 1.0 - nearest_distance((c["x"], c["y"]), cores) / 0.35) for c in cranes) / len(cranes)
    storage_score = 0.0
    if storages:
        anchors = {"core", "crane"}
        storage_score = sum(max(0.0, 1.0 - nearest_distance((s["x"], s["y"]), facilities, anchors) / 0.4) for s in storages) / len(storages)
    worker_score = 0.0
    if worker and entrance_points:
        worker_score = sum(max(0.0, 1.0 - min(math.hypot(w["x"] - e[0], w["y"] - e[1]) for e in entrance_points) / 0.35) for w in worker) / len(worker)
    efficiency = (crane_core_score + storage_score + worker_score) / max(1, int(bool(cranes and cores)) + int(bool(storages)) + int(bool(worker and entrance_points)))

    xs = [f["x"] for f in facilities]
    ys = [f["y"] for f in facilities]
    spread = (max(xs) - min(xs) + max(ys) - min(ys)) / 2 if facilities else 0.0
    adaptability = min(1.0, 0.35 + spread)

    if worker and operational:
        worker_operational = sum(nearest_distance((w["x"], w["y"]), operational) for w in worker) / len(worker)
    else:
        worker_operational = 0.5
    module_dispersion = 0.0
    pair_count = 0
    for i, first in enumerate(facilities):
        for second in facilities[i + 1 :]:
            module_dispersion += math.hypot(first["x"] - second["x"], first["y"] - second["y"])
            pair_count += 1
    module_dispersion = min(1.0, module_dispersion / max(1, pair_count) * 2.0)

    objectives = {
        "safety_compliance": round(safety, 4),
        "operational_efficiency": round(efficiency, 4),
        "layout_adaptability": round(adaptability, 4),
    }
    combined = (
        objectives["safety_compliance"] * weights.get("safety", 0.4)
        + objectives["operational_efficiency"] * weights.get("efficiency", 0.35)
        + objectives["layout_adaptability"] * weights.get("adaptability", 0.25)
    )
    objectives["combined_score"] = round(combined, 4)

    behaviors = {
        "module_dispersion": round(module_dispersion, 4),
        "worker_operational_separation": round(min(1.0, worker_operational * 2.0), 4),
    }
    feasibility = {"safe": not violations, "violations": violations}
    return Candidate(facilities, entrances, objectives, behaviors, feasibility, combined)


def generate_candidate(definition: dict[str, Any], rng: random.Random) -> Candidate:
    polygon = normalize_polygon(definition)
    if definition.get("optimisation", {}).get("randomise_entrances", False):
        entrances = generate_random_entrances(definition, polygon, rng)
    else:
        entrances = normalize_entrances(definition)
    exclusion_zones = normalize_exclusion_zones(definition)
    sequence = build_facility_sequence(definition)
    facilities: list[dict[str, Any]] = []

    for item in sequence:
        bias = "center" if item["type"] in {"core", "crane"} else "entrance" if item["type"] in {"office", "rest_area"} else "random"
        placed = None
        last_candidate = None
        for _ in range(500):
            x, y = sample_point(rng, polygon, bias, entrances)
            rotation = 90 if rng.random() < 0.35 else 0
            width = item["length"] if rotation == 90 else item["width"]
            length = item["width"] if rotation == 90 else item["length"]
            candidate = {
                "type": item["type"],
                "x": x,
                "y": y,
                "width": width,
                "length": length,
                "rotation": rotation,
                "category": facility_category(item["type"]),
                "height_m": item["height_m"],
                "clearance_radius_m": item["clearance_radius_m"],
            }
            last_candidate = candidate
            if item["type"] == "crane":
                candidate["jib_length_m"] = 6.0
                candidate["danger_radius_m"] = item["danger_radius_m"]
                candidate["optimal_reach_m"] = item["optimal_reach_m"]
                candidate["operating_radius_m"] = item["operating_radius_m"]
            if not facility_inside_boundary(candidate, polygon):
                continue
            if intersects_exclusion_zones(candidate, exclusion_zones):
                continue
            if all(not rects_overlap(candidate, existing, padding=max(0.004, item["clearance"] * 0.3)) for existing in facilities):
                placed = candidate
                break
        if placed is None:
            placed = last_candidate
        facilities.append(placed)

    objectives = definition.get("objectives", {})
    weights = {
        "safety": float(objectives.get("safety", 0.4)),
        "efficiency": float(objectives.get("efficiency", 0.35)),
        "adaptability": float(objectives.get("adaptability", 0.25)),
    }
    return score_candidate(facilities, polygon, entrances, exclusion_zones, weights)


def select_diverse(candidates: list[Candidate], count: int, grid_size: int) -> list[Candidate]:
    cells: dict[tuple[int, int], Candidate] = {}
    for candidate in sorted(candidates, key=lambda item: item.score, reverse=True):
        b1 = int(min(grid_size - 1, max(0, candidate.behaviors["module_dispersion"] * grid_size)))
        b2 = int(min(grid_size - 1, max(0, candidate.behaviors["worker_operational_separation"] * grid_size)))
        key = (b1, b2)
        if key not in cells or candidate.score > cells[key].score:
            cells[key] = candidate

    selected = sorted(cells.values(), key=lambda item: item.score, reverse=True)
    if len(selected) < count:
        seen = {id(item) for item in selected}
        for candidate in sorted(candidates, key=lambda item: item.score, reverse=True):
            if id(candidate) not in seen:
                selected.append(candidate)
                seen.add(id(candidate))
            if len(selected) >= count:
                break
    return selected[:count]


def render_preview(path: Path, layout: dict[str, Any]) -> None:
    try:
        import matplotlib.pyplot as plt
        from matplotlib.patches import Circle, Polygon, Rectangle
    except Exception:
        return

    fig, ax = plt.subplots(figsize=(5, 4.2), dpi=130)
    polygon = layout["boundary_polygon"]
    closed = polygon + [polygon[0]]
    ax.plot([p[0] for p in closed], [p[1] for p in closed], color="black", linewidth=1.8)
    ax.fill([p[0] for p in closed], [p[1] for p in closed], color="#f8efe3", alpha=0.65)
    for zone in layout.get("exclusion_zones", []):
        zone_polygon = zone.get("polygon", [])
        if len(zone_polygon) >= 3:
            ax.add_patch(Polygon(zone_polygon, closed=True, facecolor="#f7df3e", edgecolor="#c9a400", linewidth=0.9, alpha=0.62, zorder=1))
    for entrance in layout.get("entrances", []):
        ax.scatter([entrance["x"]], [entrance["y"]], marker="*", s=120, color="#f59e0b", edgecolor="#9a5a00", zorder=6)
        ax.text(entrance["x"], entrance["y"] - 0.035, "ENTRANCE", ha="center", va="top", color="#f59e0b", fontsize=6, fontweight="bold", zorder=6)
    for facility in layout["facilities"]:
        if facility["type"] == "crane":
            radius_m = float(facility.get("danger_radius_m") or facility.get("clearance_radius_m") or 0.0)
            if radius_m > 0:
                avg_dimension = (float(layout.get("site_width_m", 1.0)) + float(layout.get("site_length_m", 1.0))) / 2
                ax.add_patch(Circle((facility["x"], facility["y"]), radius_m / avg_dimension, fill=False, color="#ff2b2b", linewidth=1.3, alpha=0.78, zorder=2))
        x = facility["x"] - facility["width"] / 2
        y = facility["y"] - facility["length"] / 2
        rect = Rectangle((x, y), facility["width"], facility["length"], facecolor=FACILITY_COLORS_2D.get(facility["type"], "#64748b"), edgecolor="black", alpha=0.78, zorder=4)
        ax.add_patch(rect)
        ax.text(facility["x"], facility["y"], FACILITY_LABELS_2D.get(facility["type"], facility["type"][0].upper()), ha="center", va="center", color="white", fontsize=7, fontweight="bold", zorder=5)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_aspect("equal")
    ax.grid(alpha=0.2)
    ax.set_title(f"{layout['id']} | score {layout['objectives']['combined_score']:.3f}", fontsize=9)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def build_layout(definition: dict[str, Any], candidate: Candidate, index: int) -> dict[str, Any]:
    return {
        "id": f"cslpelite_layout_{index:03d}",
        "coordinate_space": "normalized",
        "site_width_m": float(definition["site_width_m"]),
        "site_length_m": float(definition["site_length_m"]),
        "boundary_polygon": normalize_polygon(definition),
        "exclusion_zones": normalize_exclusion_zones(definition),
        "objectives": candidate.objectives,
        "behaviors": candidate.behaviors,
        "feasibility": candidate.feasibility,
        "facilities": candidate.facilities,
        "entrances": candidate.entrances,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("definition", type=Path, help="Stage 1 problem-definition JSON exported from the GUI.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "output" / "stage1_generated_layouts")
    parser.add_argument("--count", type=int, default=None)
    parser.add_argument("--candidates", type=int, default=None)
    parser.add_argument("--grid-size", type=int, default=12)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-previews", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    definition = load_json(args.definition)
    target_count = args.count or int(definition.get("optimisation", {}).get("target_layout_count", 20))
    candidate_count = args.candidates or max(target_count * 80, 300)
    rng = random.Random(args.seed)

    candidates = [generate_candidate(definition, rng) for _ in range(candidate_count)]
    selected = select_diverse(candidates, target_count, args.grid_size)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for index, candidate in enumerate(selected):
        layout = build_layout(definition, candidate, index)
        layout_path = args.output_dir / f"cslpelite_layout_{index:03d}.json"
        write_json(layout_path, layout)
        if not args.no_previews:
            render_preview(layout_path.with_suffix(".png"), layout)

    report = {
        "stage": "stage1_layout_generation",
        "definition": str(args.definition),
        "output_dir": str(args.output_dir),
        "seed": args.seed,
        "candidate_count": candidate_count,
        "layout_count": len(selected),
        "safe_count": sum(1 for item in selected if item.feasibility["safe"]),
        "best_score": max((item.score for item in selected), default=0.0),
    }
    write_json(args.output_dir / "generation_report.json", report)
    print(f"Generated {len(selected)} layout JSONs in {args.output_dir}")
    print(f"Safe layouts: {report['safe_count']}/{report['layout_count']}")


if __name__ == "__main__":
    main()
