from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v1 as components


REPO_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_ROOT = REPO_ROOT / "pipeline"
DEFAULTS_PATH = PIPELINE_ROOT / "config" / "facility_defaults.json"
PRESETS_PATH = PIPELINE_ROOT / "config" / "cexo_presets.json"
STANDARD_VIEWER_TEMPLATE_PATH = Path(__file__).resolve().parent / "app_interface" / "layout_viewer_3d_standard.html"
BULLEEN_VIEWER_TEMPLATE_PATH = Path(__file__).resolve().parent / "app_interface" / "layout_viewer_3d_bulleen.html"
RUNS_ROOT = REPO_ROOT / "output" / "streamlit_combined_runs"

PRESET_STANDARD = "Standard case study"
PRESET_BULLEEN = "Bulleen case study"
PRESET_CUSTOM = "Custom site"
PRESET_NAMES = [PRESET_STANDARD, PRESET_BULLEEN, PRESET_CUSTOM]
PRESET_KEY_BY_NAME = {PRESET_STANDARD: "standard", PRESET_BULLEEN: "bulleen"}

CEXO_ENV_VAR = "CEXO_ROOT"

SITE_DESIGNER_COMPONENT = components.declare_component(
    "site_designer_component",
    path=Path(__file__).resolve().parent / "site_designer_component",
)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def safe_folder_name(value: str, fallback: str = "construction_site") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    cleaned = cleaned.strip("._-")
    return cleaned[:72] or fallback


def unique_run_dir(project_name: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"run_{timestamp}_{safe_folder_name(project_name)}"
    run_dir = RUNS_ROOT / base_name
    suffix = 2
    while run_dir.exists():
        run_dir = RUNS_ROOT / f"{base_name}_{suffix}"
        suffix += 1
    return run_dir


def find_cexo_root() -> Path:
    candidates = []
    env_root = os.environ.get(CEXO_ENV_VAR)
    if env_root:
        candidates.append(Path(env_root))
    candidates.extend(
        [
            REPO_ROOT / "submodules" / "cexo",
            REPO_ROOT.parent / "CEXO",
            REPO_ROOT / "CEXO",
        ]
    )

    for candidate in candidates:
        if (candidate / "main.py").exists() and (candidate / "core").is_dir():
            return candidate

    searched = "\n".join(f"- {path}" for path in candidates)
    raise RuntimeError(
        "Could not find the official CEXO optimisation repository. "
        f"Initialise submodules, clone https://github.com/ClanPing/CEXO beside "
        f"this repository, or set the {CEXO_ENV_VAR} environment variable to "
        "the CEXO repo folder.\n\n"
        f"Searched:\n{searched}"
    )


def facility_mix_from_definition(definition: dict[str, Any]) -> str:
    ordered_types = ["core", "crane", "storage", "office", "rest_area"]
    requirements = definition.get("facility_requirements", {})
    parts = []
    for facility_type in ordered_types:
        quantity = int(requirements.get(facility_type, {}).get("quantity", 0))
        if quantity > 0:
            parts.append(f"{facility_type}={quantity}")
    if not parts:
        raise RuntimeError("No facilities were selected for optimisation.")
    return ",".join(parts)


def latest_result_child(parent: Path, prefix: str) -> Path:
    matches = [
        path
        for path in parent.glob(f"{prefix}_*")
        if path.is_dir() and any(path.glob("cslpelite_layout_*.json"))
    ]
    if not matches:
        raise RuntimeError(f"The official CEXO run finished, but no {prefix}_* result folder was found in {parent}.")
    return max(matches, key=lambda path: path.stat().st_mtime)


def open_in_file_explorer(path: Path) -> None:
    resolved = path.resolve()
    if not resolved.exists():
        st.warning(f"Folder does not exist: {resolved}")
        return
    try:
        os.startfile(str(resolved))  # type: ignore[attr-defined]
    except AttributeError:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(resolved)])
    except Exception as exc:
        st.warning(f"Could not open the folder automatically: {exc}")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


@st.cache_data(show_spinner=False)
def load_defaults() -> dict[str, Any]:
    return load_json(DEFAULTS_PATH)


@st.cache_data(show_spinner=False)
def load_presets() -> dict[str, Any]:
    return load_json(PRESETS_PATH)


def normalised_to_world(points: list[list[float]], width: float, length: float) -> list[dict[str, float]]:
    return [{"x": round(float(x) * width, 2), "y": round(float(y) * length, 2)} for x, y in points]


def rectangle_points(width: float, length: float) -> list[dict[str, float]]:
    return [{"x": 0.0, "y": 0.0}, {"x": width, "y": 0.0}, {"x": width, "y": length}, {"x": 0.0, "y": length}]


def segment_corridor(a: list[float], b: list[float], width: float) -> list[list[float]]:
    ax, ay = float(a[0]), float(a[1])
    bx, by = float(b[0]), float(b[1])
    dx, dy = bx - ax, by - ay
    length = (dx * dx + dy * dy) ** 0.5
    if length <= 1e-9:
        return []
    nx, ny = -dy / length * width / 2, dx / length * width / 2
    return [[ax + nx, ay + ny], [bx + nx, by + ny], [bx - nx, by - ny], [ax - nx, ay - ny]]


def road_exclusion_zones(preset_config: dict[str, Any], site_width: float, site_length: float) -> list[dict[str, Any]]:
    corridor_width = float(preset_config.get("road_corridor_width", 0.0))
    if corridor_width <= 0:
        return []

    zones = []
    for line_index, centerline in enumerate(preset_config.get("road_centerlines") or []):
        for segment_index in range(len(centerline) - 1):
            polygon = segment_corridor(centerline[segment_index], centerline[segment_index + 1], corridor_width)
            if not polygon:
                continue
            zones.append(
                {
                    "name": f"road_{line_index:02d}_{segment_index:02d}",
                    "polygon": [
                        {"x_m": round(x * site_width, 2), "y_m": round(y * site_length, 2), "x": x, "y": y}
                        for x, y in polygon
                    ],
                }
            )
    return zones


def preset_config(presets: dict[str, Any], preset: str) -> dict[str, Any]:
    key = PRESET_KEY_BY_NAME.get(preset)
    return presets.get("presets", {}).get(key, {}) if key else {}


def preset_site_dimensions(defaults: dict[str, Any], config: dict[str, Any]) -> tuple[float, float]:
    if config:
        return float(config.get("site_width_m", 100.0)), float(config.get("site_length_m", 100.0))
    return float(defaults["site"]["default_width_m"]), float(defaults["site"]["default_length_m"])


def preset_boundary(config: dict[str, Any], width: float, length: float) -> list[dict[str, float]]:
    if config.get("boundary_polygon"):
        return normalised_to_world(config["boundary_polygon"], width, length)
    return rectangle_points(width, length)


def preset_entrances(config: dict[str, Any], width: float, length: float) -> list[dict[str, float]]:
    if config.get("entrances"):
        return normalised_to_world(config["entrances"], width, length)
    return [{"x": round(width * 0.5, 2), "y": 0.0}]


def preset_facilities(defaults: dict[str, Any], config: dict[str, Any], width: float, length: float) -> dict[str, Any]:
    facilities = json.loads(json.dumps(defaults["facility_types"]))
    if not config:
        for item in facilities.values():
            item["quantity"] = 1
        return facilities

    average_dimension = (width + length) / 2
    for name, item in facilities.items():
        spec = config.get("facility_specs", {}).get(name)
        if not spec:
            item["quantity"] = 0
            continue
        item["quantity"] = int(spec.get("quantity", 0))
        item["width_m"] = round(float(spec.get("w", 0.05)) * width, 2)
        item["length_m"] = round(float(spec.get("d", 0.05)) * length, 2)
        item["height_m"] = float(spec.get("height_m", item.get("height_m", 3.0)))
        if name == "crane":
            danger_radius = float(spec.get("danger_radius", 0.0))
            item["clearance_radius_m"] = round(danger_radius * average_dimension, 2)
            item["danger_radius_m"] = item["clearance_radius_m"]
            if spec.get("optimal_reach") is not None:
                item["optimal_reach_m"] = round(float(spec["optimal_reach"]) * average_dimension, 2)
            if spec.get("operating_radius") is not None:
                item["operating_radius_m"] = round(float(spec["operating_radius"]) * average_dimension, 2)
    return facilities


def algorithm_defaults(presets: dict[str, Any], config: dict[str, Any], preset: str, width: float, length: float) -> dict[str, Any]:
    raw = config.get("algorithm_defaults", {})
    average_dimension = (width + length) / 2
    defaults = {
        "boundary_margin_m": round(float(raw.get("boundary_margin", 0.05)) * average_dimension, 2),
        "entrance_clearance_m": round(float(raw.get("entrance_clearance", 0.15)) * average_dimension, 2),
        "crane_safety_m": round(float(raw.get("crane_safety_distance", 0.25)) * average_dimension, 2),
        "min_entrances": int(raw.get("min_entrances", 1)),
        "max_entrances": int(raw.get("max_entrances", 3)),
        "iterations": int(raw.get("iterations", 15000)),
        "grid_size": int(raw.get("grid_size", 20)),
        "initial_population": int(raw.get("initial_population", 500)),
        "pareto_size": int(raw.get("pareto_size", 12)),
        "export_count": int(raw.get("export_count", 50 if preset != PRESET_CUSTOM else 20)),
        "randomise_entrances": preset == PRESET_STANDARD,
        "facility_labels_2d": presets.get("facility_labels_2d", {}),
        "facility_colors_2d": presets.get("facility_colors_2d", {}),
        "preset_source": config.get("source", "custom"),
    }
    if config.get("road_corridor_width") is not None:
        defaults["road_corridor_width_normalized"] = config["road_corridor_width"]
    return defaults


def preset_summary(preset: str, config: dict[str, Any]) -> str:
    if preset == PRESET_STANDARD:
        return "Standard case study uses the original rectangular CSLP setup, standard facility mix, and randomised entrances during optimisation."
    if preset == PRESET_BULLEEN:
        roads = sum(max(0, len(line) - 1) for line in config.get("road_centerlines", []))
        entrances = len(config.get("entrances", []))
        return f"Bulleen case study uses the irregular site boundary, {entrances} fixed entrances, {roads} road/access corridors, and the practical Bulleen facility mix."
    return "Custom site starts from sensible defaults. Edit the boundary, entrances, facilities, and optimisation settings before running."


def style_page() -> None:
    st.markdown(
        """
        <style>
        div[data-testid="stMetric"] {
            background: rgba(255,255,255,0.035);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 8px;
            padding: 10px 12px;
        }
        .result-card-title {
            font-size: 0.9rem;
            font-weight: 700;
            margin: 0.2rem 0 0.1rem;
        }
        .muted-small {
            color: rgba(250,250,250,0.68);
            font-size: 0.86rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def viewer_is_standard(layout: dict[str, Any]) -> bool:
    points = layout.get("boundary_polygon") or []
    if not points and not layout.get("exclusion_zones"):
        return True
    if layout.get("exclusion_zones") or len(points) != 4:
        return False
    rounded = set()
    for point in points:
        if isinstance(point, dict):
            rounded.add((round(float(point["x"]), 4), round(float(point["y"]), 4)))
        else:
            rounded.add((round(float(point[0]), 4), round(float(point[1]), 4)))
    return rounded == {(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)}


def bulleen_viewer_payload(layout: dict[str, Any]) -> dict[str, Any]:
    payload = dict(layout)
    payload.setdefault("site_width_m", 100.0)
    payload.setdefault("site_length_m", 100.0)
    payload["coordinate_space"] = "meters"
    width = float(payload["site_width_m"])
    length = float(payload["site_length_m"])

    payload["boundary_polygon"] = [[float(x) * width, float(y) * length] for x, y in payload.get("boundary_polygon", [])]
    payload["entrances"] = [{**item, "x": float(item["x"]) * width, "y": float(item["y"]) * length} for item in payload.get("entrances", [])]

    zones = []
    for zone in payload.get("exclusion_zones", []):
        zones.append({**zone, "polygon": [[float(x) * width, float(y) * length] for x, y in zone.get("polygon", [])]})
    payload["exclusion_zones"] = zones

    facilities = []
    for facility in payload.get("facilities", []):
        item = dict(facility)
        item["x"] = float(item["x"]) * width
        item["y"] = float(item["y"]) * length
        item["width"] = float(item.get("width", 0.15)) * width
        item["length"] = float(item.get("length", 0.15)) * length
        if item.get("danger_radius_m") is not None:
            item["danger_radius"] = float(item["danger_radius_m"])
        facilities.append(item)
    payload["facilities"] = facilities
    return payload


def render_3d_viewer(layout: dict[str, Any], height: int = 760) -> None:
    if viewer_is_standard(layout):
        template_path = STANDARD_VIEWER_TEMPLATE_PATH
        payload = {**layout, "coordinate_space": "normalized"}
    else:
        template_path = BULLEEN_VIEWER_TEMPLATE_PATH
        payload = bulleen_viewer_payload(layout)

    if not template_path.exists():
        st.error(f"3D viewer template missing: {template_path}")
        return

    layout_json = json.dumps(payload, default=str)
    html = template_path.read_text(encoding="utf-8").replace(
        "</body>",
        f"""
        <script>
        window.addEventListener('DOMContentLoaded', function() {{
            setTimeout(function() {{
                window.postMessage({{
                    type: 'layout_data',
                    data: {layout_json}
                }}, '*');
            }}, 200);
        }});
        </script>
        </body>
        """,
    )
    components.html(html, height=height, scrolling=False)


def load_layouts(results_dir: Path) -> list[Path]:
    return sorted(layout_dir_for_run(results_dir).glob("cslpelite_layout_*.json"))


def layout_dir_for_run(run_dir: Path) -> Path:
    candidates = [run_dir / "layouts", run_dir]
    if (run_dir / "official_cexo").exists():
        candidates.extend(sorted((run_dir / "official_cexo").glob("cexo_*"), reverse=True))
    candidates.extend(sorted(run_dir.glob("cexo_*"), reverse=True))
    candidates.append(run_dir / "bulleen_results")

    for candidate in candidates:
        if candidate.exists() and any(candidate.glob("cslpelite_layout_*.json")):
            return candidate
    return run_dir


def rebuild_layout_gallery(layout_dir: Path, limit: int = 9) -> None:
    """Keep the summary gallery consistent with the exported layout previews."""
    preview_paths = sorted(layout_dir.glob("cslpelite_layout_*.png"))[:limit]
    if not preview_paths:
        return

    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return

    cell_width = 520
    cell_height = 520
    title_height = 72
    caption_height = 34
    gap = 24
    columns = min(3, len(preview_paths))
    rows = (len(preview_paths) + columns - 1) // columns
    canvas_width = columns * cell_width + (columns + 1) * gap
    canvas_height = title_height + rows * (cell_height + caption_height) + (rows + 1) * gap

    canvas = Image.new("RGB", (canvas_width, canvas_height), "white")
    draw = ImageDraw.Draw(canvas)
    try:
        title_font = ImageFont.truetype("arial.ttf", 28)
        caption_font = ImageFont.truetype("arial.ttf", 18)
    except OSError:
        title_font = ImageFont.load_default()
        caption_font = ImageFont.load_default()

    title = f"Exported Layout Catalogue (showing {len(preview_paths)} layouts)"
    draw.text((canvas_width / 2, 36), title, anchor="mm", fill=(20, 20, 20), font=title_font)
    resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS")

    for index, path in enumerate(preview_paths):
        row, column = divmod(index, columns)
        x = gap + column * (cell_width + gap)
        y = title_height + gap + row * (cell_height + caption_height + gap)

        with Image.open(path) as source:
            image = source.convert("RGB")
            image.thumbnail((cell_width, cell_height), resampling)
            offset_x = x + (cell_width - image.width) // 2
            offset_y = y + (cell_height - image.height) // 2
            canvas.paste(image, (offset_x, offset_y))

        draw.text(
            (x + cell_width / 2, y + cell_height + 20),
            path.stem,
            anchor="mm",
            fill=(20, 20, 20),
            font=caption_font,
        )

    gallery_path = layout_dir / "diverse_layouts.png"
    temporary_path = layout_dir / "diverse_layouts.tmp.png"
    canvas.save(temporary_path)
    temporary_path.replace(gallery_path)


def scene_output_root_for_run(run_dir: Path) -> Path:
    return run_dir / "unity_scenes"


def list_run_dirs() -> list[Path]:
    if not RUNS_ROOT.exists():
        return []
    return sorted([path for path in RUNS_ROOT.glob("run_*") if path.is_dir()], reverse=True)


def run_display_name(run_dir: Path) -> str:
    layout_dir = layout_dir_for_run(run_dir)
    report_path = layout_dir / "generation_report.json"
    results_path = layout_dir / "results.json"
    scene_report_path = scene_output_root_for_run(run_dir) / "batch_report.json"
    parts = [run_dir.name.replace("run_", "")]
    if report_path.exists():
        report = load_json(report_path)
        parts.append(f"{report.get('layout_count', '?')} layouts")
        parts.append(f"{report.get('safe_count', '?')} safe")
    elif results_path.exists():
        report = load_json(results_path)
        exported = report.get("exported_layouts", {})
        stats = report.get("statistics", {})
        layout_count = exported.get("count") or len(list(layout_dir.glob("cslpelite_layout_*.json")))
        parts.append(f"{layout_count} layouts")
        if "strict_feasible_count" in stats:
            parts.append(f"{stats.get('strict_feasible_count', '?')} strict feasible")
    if scene_report_path.exists():
        report = load_json(scene_report_path)
        parts.append(f"{report.get('scene_count', '?')} Unity scenes")
    return " | ".join(parts)


def load_scene_records(run_dir: Path) -> dict[str, dict[str, Any]]:
    records = read_jsonl(scene_output_root_for_run(run_dir) / "scene_records.jsonl")
    by_layout: dict[str, dict[str, Any]] = {}
    for record in records:
        layout_stem = Path(record.get("layout", "")).stem
        if layout_stem:
            by_layout[layout_stem] = record
    return by_layout


def scene_path_for_layout(run_dir: Path, layout_path: Path) -> Path | None:
    record = load_scene_records(run_dir).get(layout_path.stem)
    if record and record.get("output"):
        output_path = Path(record["output"])
        if output_path.exists():
            return output_path
    matches = sorted((scene_output_root_for_run(run_dir) / "scenes").glob(f"{layout_path.stem}_*_unity_scene.json"))
    return matches[0] if matches else None


def log_tail(path: Path, limit: int = 6000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[-limit:]


def run_logged_process(command: list[str], cwd: Path, log_path: Path) -> subprocess.Popen:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("w", encoding="utf-8", errors="replace")
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    process._cexo_log_handle = log_handle  # type: ignore[attr-defined]
    return process


def close_logged_process(process: subprocess.Popen) -> None:
    log_handle = getattr(process, "_cexo_log_handle", None)
    if log_handle is not None:
        log_handle.close()


def score_line(layout: dict[str, Any]) -> str:
    objectives = layout.get("objectives", {})
    return (
        f"S {objectives.get('safety_compliance', 0):.2f} | "
        f"E {objectives.get('operational_efficiency', 0):.2f} | "
        f"A {objectives.get('layout_adaptability', 0):.2f}"
    )


def definition_site_dimensions(definition: dict[str, Any]) -> tuple[float, float]:
    return (
        float(definition.get("site_width_m", 100.0)),
        float(definition.get("site_length_m", 100.0)),
    )


def run_generation_with_progress(definition: dict[str, Any], count: int, seed: int, candidates: int, preset: str) -> Path:
    run_dir = unique_run_dir(str(definition.get("project_name", "")))
    layout_dir = run_dir / "layouts"
    scene_output_root = scene_output_root_for_run(run_dir)
    definition_path = run_dir / "stage1_definition.json"
    write_json(definition_path, definition)

    optimisation = definition.get("optimisation", {})
    initial_population = int(optimisation.get("initial_population", 500))
    site_width_m, site_length_m = definition_site_dimensions(definition)
    cexo_root = find_cexo_root() if preset in {PRESET_STANDARD, PRESET_BULLEEN} else None

    if preset == PRESET_STANDARD:
        official_output_base = run_dir / "official_cexo"
        stage1_command = [
            sys.executable,
            str(cexo_root / "main.py"),
            "--facility-mix",
            facility_mix_from_definition(definition),
            "--iterations",
            str(candidates),
            "--initial-pop",
            str(initial_population),
            "--seed",
            str(seed),
            "--visualize",
            "--export-count",
            str(count),
            "--output",
            str(official_output_base),
        ]
        stage1_cwd = cexo_root
        stage1_status = "Running official CEXO optimiser"
        expected_seconds = max(20.0, min(240.0, candidates / 65.0))
    elif preset == PRESET_BULLEEN:
        layout_dir = run_dir / "bulleen_results"
        stage1_command = [
            sys.executable,
            str(cexo_root / "examples" / "bulleen_study" / "main.py"),
            "--practical-bulleen",
            "--bulleen-boundary",
            "--bulleen-entrances",
            "--bulleen-roads",
            "--iterations",
            str(candidates),
            "--initial-pop",
            str(initial_population),
            "--seed",
            str(seed),
            "--export-count",
            str(count),
            "--site-width-m",
            str(site_width_m),
            "--site-length-m",
            str(site_length_m),
            "--output",
            str(layout_dir),
        ]
        stage1_cwd = cexo_root / "examples" / "bulleen_study"
        stage1_status = "Running official Bulleen CEXO optimiser"
        expected_seconds = max(30.0, min(360.0, candidates / 45.0))
    else:
        stage1_command = [
            sys.executable,
            str(PIPELINE_ROOT / "scripts" / "generate_layouts_from_definition.py"),
            str(definition_path),
            "--output-dir",
            str(layout_dir),
            "--count",
            str(count),
            "--seed",
            str(seed),
            "--candidates",
            str(candidates),
        ]
        stage1_cwd = PIPELINE_ROOT
        stage1_status = "Running custom definition generator"
        expected_seconds = max(8.0, min(90.0, candidates / 80.0))

    progress = st.progress(0, text="Preparing layout optimisation")
    status = st.empty()
    started = time.time()
    optimisation_log = run_dir / "optimisation.log"
    process = run_logged_process(stage1_command, stage1_cwd, optimisation_log)

    while process.poll() is None:
        elapsed = time.time() - started
        pct = min(62, int(8 + (elapsed / expected_seconds) * 54))
        progress.progress(pct, text=f"{stage1_status}... {elapsed:.1f}s")
        status.caption(f"Generating up to {count} exported layouts from {candidates} optimisation iterations/samples.")
        time.sleep(0.35)

    process.wait()
    close_logged_process(process)
    if process.returncode != 0:
        progress.empty()
        status.empty()
        raise RuntimeError(f"Layout generation failed. See {optimisation_log}.\n\n{log_tail(optimisation_log)}")

    if preset == PRESET_STANDARD:
        layout_dir = latest_result_child(run_dir / "official_cexo", "cexo")
    else:
        layout_dir = layout_dir_for_run(run_dir)
    rebuild_layout_gallery(layout_dir)

    progress.progress(66, text="Compiling selected layouts into Unity scene JSONs")
    status.caption("Running Stage 2: prefab, accessory, and scene-graph enrichment.")
    stage2_command = [
        sys.executable,
        str(PIPELINE_ROOT / "scripts" / "batch_generate_unity_scenes.py"),
        "--input-dir",
        str(layout_dir),
        "--output-root",
        str(scene_output_root),
        "--safe-only",
        "--mode",
        "ml_guided",
        "--seeds",
        str(seed),
    ]
    scene_log = run_dir / "scene_generation.log"
    process = run_logged_process(stage2_command, PIPELINE_ROOT, scene_log)
    stage2_started = time.time()
    stage2_expected = max(10.0, min(120.0, count * 2.2))
    while process.poll() is None:
        elapsed = time.time() - stage2_started
        pct = min(96, int(66 + (elapsed / stage2_expected) * 30))
        progress.progress(pct, text=f"Building Unity-ready scene JSONs... {elapsed:.1f}s")
        status.caption("Converting the catalogue to Stage 2 Unity scene JSONs.")
        time.sleep(0.5)

    process.wait()
    close_logged_process(process)
    if process.returncode != 0:
        progress.empty()
        status.empty()
        raise RuntimeError(f"Unity scene generation failed. See {scene_log}.\n\n{log_tail(scene_log)}")

    progress.progress(100, text="Catalogue and Unity scene JSONs ready")
    status.caption(log_tail(scene_log, 1000).strip() or log_tail(optimisation_log, 1000).strip() or "Layouts and Unity scene JSONs generated.")
    time.sleep(0.6)
    return run_dir


def render_setup_page(defaults: dict[str, Any], presets: dict[str, Any]) -> None:
    st.title("Construction Layout Generator")

    run_dirs = list_run_dirs()
    if run_dirs:
        st.subheader("Run History")
        history_options = ["Start a new definition"] + [str(path) for path in run_dirs]
        labels = {"Start a new definition": "Start a new definition"}
        labels.update({str(path): run_display_name(path) for path in run_dirs})
        selected_history = st.selectbox(
            "Open previous catalogue",
            history_options,
            format_func=lambda value: labels.get(value, value),
            key="history_selector",
        )
        history_left, history_right = st.columns([1, 1])
        with history_left:
            if selected_history != "Start a new definition" and st.button("Open selected catalogue", use_container_width=True):
                st.session_state.results_dir = selected_history
                st.session_state.focused_layout = ""
                st.session_state.page = "results"
                st.rerun()
        with history_right:
            if st.button("Clear old runs", use_container_width=True):
                shutil.rmtree(RUNS_ROOT)
                st.session_state.results_dir = ""
                st.session_state.focused_layout = ""
                st.success("Run history cleared.")
                st.rerun()
        st.markdown("---")

    preset = st.radio("Definition preset", PRESET_NAMES, horizontal=True, key="selected_preset")
    config = preset_config(presets, preset)
    site_width, site_length = preset_site_dimensions(defaults, config)
    project_name = f"{PRESET_KEY_BY_NAME.get(preset, 'custom')}_construction_site"
    st.info(preset_summary(preset, config))

    boundary = preset_boundary(config, site_width, site_length)
    entrances = preset_entrances(config, site_width, site_length)
    exclusion_zones = road_exclusion_zones(config, site_width, site_length)
    facilities = preset_facilities(defaults, config, site_width, site_length)
    algo = algorithm_defaults(presets, config, preset, site_width, site_length)

    definition = SITE_DESIGNER_COMPONENT(
        projectName=project_name,
        preset=preset,
        siteWidth=site_width,
        siteLength=site_length,
        boundary=boundary,
        initialEntrances=entrances,
        initialExclusionZones=exclusion_zones,
        facilityTypes=facilities,
        algorithmDefaults=algo,
        entranceEditingEnabled=preset != PRESET_STANDARD,
        default=None,
        key=f"designer_{preset}",
    )

    st.markdown("---")
    st.subheader("Run Optimisation")
    default_run_index = 0 if preset == PRESET_BULLEEN else 1
    run_mode = st.radio(
        "Run length",
        ["Quick", "Balanced", "Thorough"],
        index=default_run_index,
        horizontal=True,
        key=f"run_mode_{preset}",
    )

    cexo_iterations = int(algo.get("iterations", 15000))
    mode_defaults = {
        "Quick": {"count": min(12, int(algo["export_count"])), "candidates": int(algo.get("initial_population", 500))},
        "Balanced": {"count": min(50, int(algo["export_count"])), "candidates": cexo_iterations},
        "Thorough": {"count": min(100, max(int(algo["export_count"]), 50)), "candidates": max(cexo_iterations * 2, 30000)},
    }[run_mode]

    col1, col2, col3 = st.columns(3)
    with col1:
        count = st.number_input(
            "Layouts to export",
            min_value=1,
            max_value=200,
            value=mode_defaults["count"],
            step=1,
            key=f"layout_count_{preset}_{run_mode}",
        )
    with col2:
        candidates = st.number_input(
            "Optimisation iterations",
            min_value=100,
            max_value=100000,
            value=mode_defaults["candidates"],
            step=100,
            key=f"candidate_samples_{preset}_{run_mode}",
        )
    with col3:
        seed = st.number_input("Seed", min_value=0, max_value=999999, value=42, step=1, key=f"seed_{preset}")

    if preset == PRESET_STANDARD:
        st.caption("Standard mode runs the official CEXO optimiser and forwards the selected facility counts as a facility mix.")
    elif preset == PRESET_BULLEEN:
        st.caption(
            "Bulleen mode runs the official optimiser with fixed case-study boundary, entrances, and road exclusions. "
            "Use Quick for dashboard preview; Balanced and Thorough can take much longer because they run learned-descriptor optimisation."
        )

    if st.button("Run Optimisation", type="primary", use_container_width=True, disabled=definition is None):
        run_definition = dict(definition)
        run_definition.setdefault("optimisation", {})
        run_definition["optimisation"]["target_layout_count"] = int(count)
        run_definition["optimisation"]["randomise_entrances"] = preset == PRESET_STANDARD
        try:
            run_dir = run_generation_with_progress(run_definition, int(count), int(seed), int(candidates), preset)
        except Exception as exc:
            st.error(str(exc))
            return
        st.session_state.results_dir = str(run_dir)
        st.session_state.focused_layout = ""
        st.session_state.page = "results"
        st.rerun()


def render_focused_preview(layout_path: Path) -> None:
    layout = load_json(layout_path)
    image_path = layout_path.with_suffix(".png")
    st.title(f"Focused Layout: {layout_path.stem}")
    st.caption(score_line(layout))

    mode = st.radio("Preview mode", ["2D", "3D", "Side-by-side"], horizontal=True, key=f"preview_{layout_path}")
    if mode == "2D":
        if image_path.exists():
            st.image(str(image_path), use_container_width=True)
        else:
            st.warning("2D preview image is missing.")
    elif mode == "3D":
        render_3d_viewer(layout)
    else:
        left, right = st.columns(2)
        with left:
            if image_path.exists():
                st.image(str(image_path), use_container_width=True)
            else:
                st.warning("2D preview image is missing.")
        with right:
            render_3d_viewer(layout, height=620)


def render_focus_page() -> None:
    layout_path = Path(st.session_state.get("focused_layout", ""))
    run_dir = Path(st.session_state.get("results_dir", ""))
    if not layout_path.exists():
        st.error("The selected layout could not be found.")
        if st.button("Back to results"):
            st.session_state.page = "results"
            st.rerun()
        return

    left, right = st.columns([1, 1])
    with left:
        if st.button("Back to results", use_container_width=True):
            st.session_state.page = "results"
            st.rerun()
    with right:
        if st.button("Open results folder", use_container_width=True):
            open_in_file_explorer(run_dir)

    if st.button("Back to definition", use_container_width=True):
        st.session_state.page = "setup"
        st.rerun()

    scene_path = scene_path_for_layout(run_dir, layout_path)
    if scene_path and scene_path.exists():
        with scene_path.open("rb") as handle:
            st.download_button(
                "Download Unity scene JSON",
                data=handle.read(),
                file_name=scene_path.name,
                mime="application/json",
                type="primary",
                use_container_width=True,
            )
    else:
        st.warning("Unity scene JSON is missing for this layout.")

    render_focused_preview(layout_path)


def render_results_page() -> None:
    results_dir = Path(st.session_state.get("results_dir", ""))
    if not results_dir.exists():
        st.error("No generated results are available yet.")
        if st.button("Back to setup"):
            st.session_state.page = "setup"
            st.rerun()
        return

    st.title("Generated Scene Catalogue")
    st.caption(f"Run folder: `{results_dir}`")

    layout_paths = load_layouts(results_dir)
    if not layout_paths:
        st.warning("No layout JSON files were found.")
        return

    layout_dir = layout_dir_for_run(results_dir)
    report_path = layout_dir / "generation_report.json"
    results_path = layout_dir / "results.json"
    scene_report_path = scene_output_root_for_run(results_dir) / "batch_report.json"
    report = load_json(report_path) if report_path.exists() else {}
    official_results = load_json(results_path) if results_path.exists() else {}
    scene_report = load_json(scene_report_path) if scene_report_path.exists() else {}
    if official_results and not report:
        exported = official_results.get("exported_layouts", {})
        stats = official_results.get("statistics", {})
        report = {
            "layout_count": exported.get("count", len(layout_paths)),
            "safe_count": exported.get("count", len(layout_paths)) if exported.get("strict_feasible_only", True) else stats.get("strict_feasible_count", "-"),
            "best_score": stats.get("best_scalar_fitness", 0.0),
        }
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Layouts", report.get("layout_count", len(layout_paths)))
    col2.metric("Safe", f"{report.get('safe_count', '-')}/{report.get('layout_count', len(layout_paths))}")
    col3.metric("Unity scenes", scene_report.get("scene_count", "-"))
    col4.metric("Best score", f"{float(report.get('best_score', 0.0)):.3f}")

    top_left, top_mid, top_right = st.columns([1, 1, 1])
    with top_left:
        if st.button("Back to definition", use_container_width=True):
            st.session_state.page = "setup"
            st.rerun()
    with top_mid:
        if st.button("Open results folder", use_container_width=True):
            open_in_file_explorer(results_dir)
    with top_right:
        if st.button("Start a new run", type="primary", use_container_width=True):
            st.session_state.page = "setup"
            st.session_state.results_dir = ""
            st.session_state.focused_layout = ""
            st.rerun()

    if not st.session_state.get("focused_layout"):
        st.session_state.focused_layout = str(layout_paths[0])

    st.subheader("Catalogue")
    columns = st.columns(4)
    for index, layout_path in enumerate(layout_paths):
        layout = load_json(layout_path)
        image_path = layout_path.with_suffix(".png")
        scene_path = scene_path_for_layout(results_dir, layout_path)
        with columns[index % 4]:
            if image_path.exists():
                st.image(str(image_path), use_container_width=True)
            st.markdown(f"<p class='result-card-title'>{layout_path.stem}</p>", unsafe_allow_html=True)
            st.markdown(f"<p class='muted-small'>{score_line(layout)}</p>", unsafe_allow_html=True)
            if st.button("Focus preview", key=f"focus_{layout_path.stem}", use_container_width=True):
                st.session_state.focused_layout = str(layout_path)
                st.session_state.page = "focus"
                st.rerun()
            if scene_path and scene_path.exists():
                with scene_path.open("rb") as handle:
                    st.download_button(
                        "Download Unity scene JSON",
                        data=handle.read(),
                        file_name=scene_path.name,
                        mime="application/json",
                        key=f"download_{layout_path.stem}",
                        use_container_width=True,
                    )
            else:
                st.caption("Unity scene JSON missing")


def main() -> None:
    st.set_page_config(page_title="Construction Layout Generator", layout="wide")
    style_page()
    defaults = load_defaults()
    presets = load_presets()
    st.session_state.setdefault("page", "setup")
    st.session_state.setdefault("results_dir", "")
    st.session_state.setdefault("focused_layout", "")

    if st.session_state.page == "results":
        render_results_page()
    elif st.session_state.page == "focus":
        render_focus_page()
    else:
        render_setup_page(defaults, presets)


if __name__ == "__main__":
    main()
