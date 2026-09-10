"""Build-time answer-key collector (docs/00-design.md Sec 3.3) -- NOT exposed to
students. Runs a stage's ``submit_<problem>`` function against a reference
solution module, capturing each value passed to ``bootcode.submit()`` instead
of sending it anywhere.

Invoked by ``build-courses.ts`` as: ``python -m bootcode._internal.collect
<tests_file> <solution_file> <problem>``, printing a JSON array to stdout.
"""

from __future__ import annotations

import json
import sys

from bootcode import protocol
from bootcode._module_loader import load_module
from bootcode.harness import resolve_and_call


def collect_answer_key(tests_path: str, solution_path: str, problem: str) -> list:
    collected: list = []
    protocol.bind_collector(collected.append)
    try:
        tests_module = load_module(tests_path)
        solution_module = load_module(solution_path)
        submit_fn = getattr(tests_module, f"submit_{problem}")
        resolve_and_call(submit_fn, solution_module)
    finally:
        protocol.unbind()
    return collected


def main() -> None:
    tests_path, solution_path, problem = sys.argv[1], sys.argv[2], sys.argv[3]
    print(json.dumps(collect_answer_key(tests_path, solution_path, problem)))


if __name__ == "__main__":
    main()
