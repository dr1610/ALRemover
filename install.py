"""Install only missing inference libraries; never replace the host's PyTorch."""
from importlib.util import find_spec
import launch

for module, requirement in [
    ("timm", "timm>=1.0.0,<2"), ("kornia", "kornia>=0.6.12,<1"),
    ("einops", "einops>=0.7,<1"), ("safetensors", "safetensors>=0.4,<1"),
    ("huggingface_hub", "huggingface-hub>=0.25,<1"),
]:
    if find_spec(module) is None:
        launch.run_pip("install " + requirement, "ALRemover: " + module)
