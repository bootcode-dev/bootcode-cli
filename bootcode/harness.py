"""Reflection-based parameter injection for ``test_*``/``submit_*`` functions.

A stage's test file defines e.g. ``submit_add(add)``, and the parameter name
``add`` is resolved by attribute lookup on the student's solution module
(which defines a top-level ``add`` function/class of the same name). No
pytest, no conftest, no fixtures -- just ``inspect.signature`` + ``getattr``.
"""

from __future__ import annotations

import inspect
from types import ModuleType
from typing import Any, Callable


def resolve_and_call(test_func: Callable[..., Any], solution_module: ModuleType) -> Any:
    """Call ``test_func`` with each parameter resolved by name from ``solution_module``.

    Raises ``AttributeError`` (with the missing name in the message) if the
    solution module doesn't define one of the requested parameters -- this
    surfaces as a clear "did you implement `X`?" style failure rather than a
    silent ``TypeError`` about missing arguments.
    """
    signature = inspect.signature(test_func)
    args = [getattr(solution_module, name) for name in signature.parameters]
    return test_func(*args)
