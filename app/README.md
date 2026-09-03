# Stage 1 Layout Definition GUI

This Streamlit app combines the working Standard and Bulleen case-study
workflows into one cleaner interface, with a third Custom site mode for user
defined layouts. It treats raw layout JSON files as internal optimisation
outputs and presents Unity-ready scene JSON files as the user-facing export.

The app focuses on Stage 1 inputs:

- site dimensions
- rectangular or irregular polygon boundary
- entrance points for Bulleen and Custom sites
- road/no-go polygons
- facility quantities and dimensions
- objective weights
- behavioural descriptors
- optimisation run settings
- crowding and feasibility preview

The interface is split into three screens:

- Definition: choose Standard, Bulleen, or Custom; edit the site boundary,
  facility requirements, and run length. Bulleen and Custom also expose manual
  entrance editing.
- Results: inspect the generated scene catalogue, reopen previous timestamped
  runs, open the run folder in File Explorer, and download Unity scene JSON
  files for selected layouts.
- Focused preview: inspect one result at a time and switch between 2D, 3D, and
  side-by-side previews without scrolling through the full gallery. The focused
  result also exposes the Unity scene JSON download.

Rectangular standard layouts use the original clean standard-case 3D viewer,
while irregular or road-constrained layouts use the Bulleen-capable viewer.
Unity remains the Stage 2 viewer for prefab-based construction scene
visualisation.

The two built-in presets are mirrored from the current CEXO reference setup:

- `Standard case study` follows the external `ClanPing/CEXO` `core/config.py` and
  randomises entrances during optimisation, matching the previous standalone
  standard Streamlit workflow. Manual entrance controls are hidden for this
  preset because the final entrances are solver-generated.
- `Bulleen case study` follows the external `ClanPing/CEXO`
  `examples/bulleen_study/core/config.py`,
  including the irregular boundary, three fixed entrances, road/access
  exclusion corridors, Bulleen facility mix, crane radii, facility labels, and
  facility colours.

Each run is saved locally under `output/streamlit_combined_runs/run_*`.
The project name is included in the run folder name after being cleaned for
safe filesystem usage, for example
`run_20260902_143000_bulleen_construction_site`.
Project name and workspace dimensions are edited inside the site editor so the
definition has one source of truth.
The app keeps previous runs available through Run History until the user clicks
Clear old runs.

The Balanced run-length default uses the CEXO standard iteration count
(`15000` optimisation samples). Quick uses the CEXO initial population size
(`500`) for fast UI testing.

## Run

From the repository root:

```powershell
python run_app.py
```

For Standard and Bulleen optimisation runs, clone
`https://github.com/ClanPing/CEXO` beside this repository or set `CEXO_ROOT` to
the local CEXO folder. Custom site runs use the lightweight generator included
in this repository.

The GUI works in metres and exports both world coordinates and normalised
coordinates. The normalised coordinates match the layout JSON convention used by
the existing Stage 2 scene compiler.
