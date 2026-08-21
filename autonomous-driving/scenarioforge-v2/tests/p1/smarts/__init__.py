"""Isolated P1 tests that preserve access to the installed SMARTS package."""

from importlib.metadata import distribution, version
from pathlib import Path


# Pytest needs a package boundary because this directory and ``tests/`` both
# contain ``test_reproducibility.py``.  The package is necessarily named
# ``smarts``, so keep the installed distribution first (its configuration uses
# the first package path to resolve engine assets) and this test package second.
_TEST_PACKAGE = Path(__file__).resolve().parent
_INSTALLED_PACKAGE = Path(distribution("smarts").locate_file("smarts")).resolve()
__path__ = [str(_INSTALLED_PACKAGE), str(_TEST_PACKAGE)]
VERSION = version("smarts")
