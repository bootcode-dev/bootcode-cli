"""bootcode -- CLI for bootcode's cli-hidden grading protocol.

Adapted stage test files do ``import bootcode`` and call ``bootcode.submit(value)``
once per graded value inside a ``submit_<problem>`` function -- re-exported here
so that call site works without reaching into ``bootcode.protocol`` directly.
"""

from bootcode.protocol import submit

__all__ = ["submit"]
