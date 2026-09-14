"""Install only missing inference libraries; never replace the host's PyTorch."""
from importlib.util import find_spec
import subprocess
import sys

launch = __import__("launch") if find_spec("launch") is not None else None

for module, requirement in [
    ("timm", "timm>=1.0.0,<2"), ("kornia", "kornia>=0.6.12,<1"),
    ("einops", "einops>=0.7,<1"), ("safetensors", "safetensors>=0.4,<1"),
    ("huggingface_hub", "huggingface-hub>=0.25,<2"),
    ("cv2", "opencv-python-headless>=4.10,<5"),
]:
    if find_spec(module) is None:
        if launch is not None:
            launch.run_pip("install " + requirement, "ALRemover: " + module)
        else:
            subprocess.check_call([sys.executable, "-m", "pip", "install", requirement])
