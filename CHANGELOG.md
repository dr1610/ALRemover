# Changelog

## 1.4.0-beta.1 — ComfyUI support

- Add ComfyUI nodes for cutout, local keep/erase correction and character/background RGBA layers. Standard Preview Image and Save Image nodes handle display and PNG export.
- Include basic and correction workflows, a Mask Editor guide, and a reproducible ComfyUI API test.
- Preserve original RGB and existing alpha; follow ComfyUI's inverse-alpha convention at Load Image inputs. Mask corrections reuse ComfyUI's cached extraction result.
- Honor ComfyUI's selected device and free memory through its model manager before inference. Release the extension's CPU model cache after each cutout node execution.
- Use BEN2's float32 preprocessing on non-CUDA devices, including explicit CPU selection on CUDA-capable machines.
- Let the installer run under either host, without pinning or replacing host Torch/Transformers versions.
- Keep the existing Neo tab and Script integration. Multi-person tools remain Neo-only and experimental.

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
