import platform
import shutil
import os
import subprocess
from pathlib import Path
import sys


def __dap_path():
    is_debug = False
    # is_debug = True
    folder = "debug" if is_debug else "release"

    dap_path = str(Path.home() / f"Dev/contribute/llvm-build/{folder}/bin/lldb-dap")
    if sys.platform == "darwin":
        dap_path = f"/Volumes/workspace/Dev/llvm-build/{folder}/bin/lldb-dap"
    return dap_path


test_build_dir: Path = Path(os.getcwd()) / "builds"
cmake_build_type: str = "release" if "release" in __dap_path() else "debug"
arch = platform.machine()


lldbDAPExec: str = os.getenv("DAP_ADAPTER_PATH", __dap_path())


def get_yaml2obj_path() -> str:
    yaml2obj = shutil.which("yaml2obj")
    if not yaml2obj:
        yaml2obj = subprocess.check_output(
            ["xcrun", "-f", "yaml2obj"], text=True
        ).strip()

    assert yaml2obj is not None
    return yaml2obj
