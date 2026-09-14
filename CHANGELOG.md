# Changelog

## 1.3.0-beta.1 — ALRemover public beta

- Rename the product to **ALRemover**. The main workflow is one character: extract, correct locally, save.
- Keep BEN2 as the default. Mark multi-person separation as experimental and keep its Script switch off by default.
- Retain separate character/background preview and PNG saving, original-resolution editing, and green/red local correction.
- Retain ToonOut and both cascade orders as optional comparison modes; cascades may thin hair.
- Add public installation instructions, the project MIT license, and a reproducible clean-environment verification procedure.
- Create Neo's configured preview directory before building the UI, fixing the first result display on a fresh installation without a pre-existing temporary directory.
- Add explicit, labeled keep/erase brush selection. This updates the editor's default color without replacing its image/strokes, avoiding palette color resets observed in Gradio 4.40.
- New tab exports use `outputs/ALRemover/`. Existing files are not moved. Internal `alr_neo` API identifiers and the `models/AnimeLayerRemoverNeo/` cache remain compatible with the development builds.

## Earlier local development

- 1.2.0: experimental per-person ownership editing, local brushes, undo, PNG and project export.
- 1.1.0: BEN2 → ToonOut reverse cascade.
- 1.0.0: Script integration, BEN2/ToonOut/forward cascade, character/background export and local correction.
