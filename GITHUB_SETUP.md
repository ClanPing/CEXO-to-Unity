# GitHub Setup Notes

This repository tracks the reusable scene-generation pipeline, not every generated scene.

## Commit

- `scripts/`
- `config/`
- `models/`
- `unity/`
- `examples/`
- project documentation

## Keep Local

- `output/`
- `data/`
- Unity project cache/build folders
- full CEXO result exports

The full CEXO study folder currently lives outside this repository:

`C:\Users\Ping\Documents\Visual studio code repo\2026\CSLP v5 (official)\bulleen_study`

## First Remote Push

When ready, create an empty GitHub repository with no README, no `.gitignore`, and no license. Then add it as the remote:

```powershell
git remote add origin <github-repo-url>
git branch -M main
git push -u origin main
```
