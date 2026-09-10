"""Load a ``.py`` file as a module by path -- shared by ``bootcode.cli`` (student
runs) and ``bootcode._internal.collect`` (build-time answer-key generation), both
of which need to import a solution/test file that isn't installed as a package.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def load_module(path: str | Path) -> ModuleType:
    module_path = Path(path)
    # Puts the stage directory on sys.path (once) so a solution/test file can
    # `import` a sibling module in the same pulled directory (e.g. a shared
    # `polynomial.py` both poly_add.py and poly_add_tests.py import from) --
    # without this, spec_from_file_location loads module_path itself fine,
    # but any plain `import <sibling>` statement inside it fails with
    # ModuleNotFoundError, since bootcode is an installed console-script
    # (sys.path[0] is its own install location, never the student's cwd).
    parent = str(module_path.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
