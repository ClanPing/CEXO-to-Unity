# CEXO to Unity

CEXO to Unity is a prototype workflow for generating construction-site layout
alternatives and previewing selected layouts as Unity 3D scenes.

The workflow is:

```text
site definition -> optimisation / quality-diversity layout generation
-> Unity-ready scene JSON -> Unity importer preview
```

## Quick Start

Install Python dependencies:

```powershell
pip install -r requirements.txt
```

Run the Streamlit app:

```powershell
python run_app.py
```

The app lets users choose a preset case study, adjust parameters, run layout
generation, browse the resulting catalogue, and download the selected
Unity-ready scene JSON.

## Repository Layout

```text
app/          Streamlit user interface and 2D/3D preview templates
pipeline/     Layout-to-scene scripts, configs, examples, and ML checkpoints
unity/        Unity importer source, asset catalog, demo JSONs, and package
docs/         Methodology notes and figures
examples/     Small shareable input examples
data/         Local raw layout datasets, ignored by git
output/       Local generated runs, ignored by git
```

## CEXO Optimisation Dependency

The official optimisation / quality-diversity generator is maintained in the
separate [ClanPing/CEXO](https://github.com/ClanPing/CEXO) repository.

For Standard and Bulleen preset optimisation runs, either clone `CEXO` beside
this repository:

```text
2026/
  CEXO/
  CEXO-to-Unity/
```

or set `CEXO_ROOT` to the local CEXO folder before running the app:

```powershell
$env:CEXO_ROOT = "C:\path\to\CEXO"
python run_app.py
```

The Custom site mode and Stage 2 Unity scene conversion live in this repository.

## Unity Scene JSON Source

The JSON file users should load into Unity is the Stage 2 Unity-ready scene
JSON, not the raw optimisation layout JSON.

Streamlit saves generated scene JSONs here:

```text
output/streamlit_combined_runs/<run_name>/unity_scenes/scenes/*_unity_scene.json
```

The matching run report is:

```text
output/streamlit_combined_runs/<run_name>/unity_scenes/batch_report.json
```

## Unity Preview

Import the package into a Unity project:

```text
unity/CEXOToUnityImporter.unitypackage
```

Then open:

```text
Tools > CEXO to Unity > Scene Browser
```

Use `Import Scene JSON...` to load one downloaded scene JSON directly, or use
`Generated Scene Folder` to browse a catalogue of `*_unity_scene*.json` files.

## Asset Pack Note

The tested prefab paths target the Unity Asset Store package
`Construction Site SilverTM`. This repository does not redistribute the paid
asset pack. Users can install that package, use generated placeholders for
missing prefabs, or edit `unity/StreamingAssets/cexo_asset_catalog.json` to
remap generated asset names to their own Unity prefabs.

For detailed methodology and command-line pipeline usage, see
`docs/PIPELINE.md`.
