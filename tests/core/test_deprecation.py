"""Importing the package tells the user where the project went."""

import subprocess
import sys


def test_import_warns_about_the_replacement():
    # A fresh interpreter: the package is already imported here, and a module warns only once.
    result = subprocess.run([sys.executable, "-c", "import sd_model_hub"], capture_output=True, text=True, check=True)
    assert "FutureWarning" in result.stderr
    assert "pip install hanakura" in result.stderr
