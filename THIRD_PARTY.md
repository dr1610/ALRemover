# Third-party code and weights

The original ToonOut/BiRefNet/BEN2 components use MIT licenses. Upstream license texts are retained in `licenses/`.

| Component | Pinned source | Files / use |
|---|---|---|
| ToonOut weights | [joelseytre/toonout](https://huggingface.co/joelseytre/toonout/tree/cbf720eca394edcde66b861a8a8c20fbabe9c748) | `birefnet_finetuned_toonout.pth` |
| ToonOut reference implementation | [MatteoKartoon/BiRefNet](https://github.com/MatteoKartoon/BiRefNet/tree/ba5d19a7bf16b1ea7746bb9e9bec83d97dad9709) | Benchmark reference, MIT notice |
| BiRefNet inference architecture | [ZhengPeng7/BiRefNet_HR](https://huggingface.co/ZhengPeng7/BiRefNet_HR/tree/a7a562f6fd16021180f2f4348f4de003a2d3d1e1) | Vendored `birefnet.py`, `BiRefNet_config.py`. Used at 1024 px with ToonOut weights. **No HR weights used.** |
| BEN2 | [PramaLLC/BEN2](https://huggingface.co/PramaLLC/BEN2/tree/e48a20765fb421d19dcdb0bf3cc61e802ca5ec8f) | Vendored `BEN2.py` renamed `ben2.py`; `model.safetensors` |

Vendored files are unmodified (except the BEN2 module filename). Inference wrappers preserve host RNG and backend settings around imports, model construction, and inference.
Weights are loaded locally with strict state-dict matching; ToonOut uses `torch.load(weights_only=True)` and BEN2 uses Safetensors.
Hugging Face remote-code execution is not enabled.
The flattened BiRefNet architecture produced exactly the same ToonOut alpha as the original ToonOut implementation on both regression images.
