import shutil
import os
import subprocess
from pathlib import Path


test_build_dir: Path = Path(os.getcwd()) / "builds"

def get_yaml2obj_path() -> str:
    yaml2obj = shutil.which("yaml2obj") 
    if not yaml2obj:
        yaml2obj = subprocess.check_output(["xcrun", "-f", "yaml2obj"], text=True).strip()

    assert yaml2obj is not None
    return yaml2obj