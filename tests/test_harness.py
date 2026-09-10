from types import SimpleNamespace

import pytest

from bootcode.harness import resolve_and_call


def test_resolve_and_call_injects_by_parameter_name():
    solution = SimpleNamespace(add=lambda a, b: a + b)

    def submit_add(add):
        return add(2, 3)

    assert resolve_and_call(submit_add, solution) == 5


def test_resolve_and_call_supports_multiple_parameters_in_order():
    solution = SimpleNamespace(add=lambda a, b: a + b, primes=lambda n: list(range(n)))

    def submit_two(add, primes):
        return add(1, 1), primes(3)

    assert resolve_and_call(submit_two, solution) == (2, [0, 1, 2])


def test_resolve_and_call_raises_a_clear_error_when_solution_is_incomplete():
    solution = SimpleNamespace()  # student never defined `add`

    def submit_add(add):
        return add(2, 3)

    with pytest.raises(AttributeError):
        resolve_and_call(submit_add, solution)
