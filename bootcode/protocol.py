"""Client-side submission protocol.

``encode_json`` turns arbitrary Python values (including numpy arrays/scalars,
``datetime``, and ``type`` objects) into a JSON-safe structure the server's
tolerance-aware comparator can decode. ``submit(value)`` is the single
module-level function adapted stage test files call once per graded value --
it delegates to whatever session is currently ``bind()``-ed, so the same
``submit_<problem>`` function body works identically for a real graded
submission (``bootcode submit``) and for the build-time answer-key collector
(``bootcode._internal.collect``): both are collect-only, no per-value network
call -- ``bootcode submit`` POSTs the whole collected list once, via
``submit_batch()`` below, after ``submit_<problem>`` returns).
"""

from __future__ import annotations

import datetime
from typing import Any, Callable, Protocol

import requests

try:
    import numpy as np
except ImportError:  # numpy is only needed by stages that actually use it
    np = None  # type: ignore[assignment]

DEFAULT_TIMEOUT_S = 30


def encode_json(data: Any) -> Any:
    """Recursively encode ``data`` into a JSON-safe structure.

    Non-JSON-native types are wrapped in a ``{"_encoded_type": ..., "data": ...}``
    envelope; the server-side comparator decodes the same envelopes before
    applying exact/tolerance comparison.
    """
    if isinstance(data, dict):
        return {key: encode_json(value) for key, value in data.items()}
    if isinstance(data, (list, tuple)):
        return [encode_json(value) for value in data]
    if isinstance(data, datetime.datetime):
        return {"_encoded_type": "datetime", "data": data.isoformat()}
    if isinstance(data, type):
        return {"_encoded_type": "type", "data": repr(data)}
    if np is not None:
        if isinstance(data, np.ndarray):
            return {"_encoded_type": "np.ndarray", "data": encode_json(data.tolist())}
        if isinstance(data, np.dtype):
            return {"_encoded_type": "type", "data": repr(data)}
        if isinstance(data, np.floating):
            return float(data)
        if isinstance(data, np.integer):
            return int(data)
    return data


class _Session(Protocol):
    """Anything with a ``submit_value`` method can be bound as the active
    session. Both the real ``bootcode submit`` flow and the build-time
    collector bind a ``_CollectingSession`` -- there is no networked
    per-value session anymore; the network call happens exactly once, after
    ``submit_<problem>`` returns, via ``submit_batch()``."""

    def submit_value(self, value: Any) -> bool: ...


class _CollectingSession:
    """Records the ``encode_json``-encoded value, makes no network call, and
    always reports ``True`` (there's no server verdict to report yet --
    either this is build-time answer-key collection, or it's a real
    ``bootcode submit`` run whose values are POSTed as a batch only after
    ``submit_<problem>`` returns, see ``submit_batch()``)."""

    def __init__(self, on_value: Callable[[Any], None]) -> None:
        self._on_value = on_value

    def submit_value(self, value: Any) -> bool:
        self._on_value(encode_json(value))
        return True


_active: _Session | None = None


def bind(session: _Session) -> None:
    """Activate a session for the current process -- must be called before
    any adapted ``submit_<problem>`` function runs."""
    global _active
    _active = session


def bind_collector(on_value: Callable[[Any], None]) -> None:
    """Convenience wrapper around ``bind()`` -- used both for build-time
    answer-key collection and for a real ``bootcode submit`` run's local
    value collection."""
    bind(_CollectingSession(on_value))


def unbind() -> None:
    global _active
    _active = None


def submit(value: Any) -> bool:
    """Called by adapted ``submit_<problem>`` functions. Raises if no session
    has been bound yet."""
    if _active is None:
        raise RuntimeError("bootcode.submit() called with no active session -- run via `bootcode submit`")
    return _active.submit_value(value)


def submit_batch(
    api_url: str, cli_token: str, course_slug: str, stage_slug: str, values: list[Any]
) -> requests.Response:
    """POST every value collected during one ``bootcode submit`` run in a
    single request (batch, not streaming -- this replaced an earlier
    per-value ``/start`` + ``/submit_test`` protocol). ``values``
    must already be ``encode_json``-encoded (e.g. collected via
    ``bind_collector``). Returns the raw response -- the caller is
    responsible for both rendering ``response.json()["test_run"]["raw_results"]``
    and calling ``raise_for_status()``."""
    return requests.post(
        f"{api_url}/api/cli/courses/{course_slug}/stages/{stage_slug}/submit",
        headers={"Authorization": f"Bearer {cli_token}"},
        json={"values": values},
        timeout=DEFAULT_TIMEOUT_S,
    )
