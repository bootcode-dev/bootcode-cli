"""Reads/writes ``.bootcode/stage.json`` in the current directory -- written by
``bootcode pull``, read by ``bootcode run``/``submit``.

``entry``/``tests_file`` are required in practice: ``run``/``submit`` need to
know which local files to import without another network round-trip, and
one-stage-one-problem means there's exactly one of each per stage.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

_STAGE_DIR = ".bootcode"
_STAGE_FILE = "stage.json"


@dataclass
class Stage:
    course_slug: str
    stage_slug: str
    entry: str
    tests_file: str
    # Optional (added after the field above shipped): missing entirely on
    # `.bootcode/stage.json` files written by older bootcode versions --
    # `Stage.load()`'s `cls(**json.loads(...))` needs a default so those
    # still parse. Used only for the pull's phase-switch hint (cli.py).
    phase: str | None = None

    @property
    def problem(self) -> str:
        """The stem of ``entry`` (e.g. ``add.py`` -> ``add``) -- the naming
        convention every pulled stage's solution/test function pair follows."""
        return Path(self.entry).stem

    @classmethod
    def load(cls, cwd: Path | None = None) -> "Stage":
        path = (cwd or Path.cwd()) / _STAGE_DIR / _STAGE_FILE
        if not path.exists():
            raise FileNotFoundError(
                f"no {_STAGE_DIR}/{_STAGE_FILE} found here -- run `bootcode pull <course-slug>/<stage-slug>` first"
            )
        return cls(**json.loads(path.read_text()))

    def save(self, cwd: Path | None = None) -> None:
        directory = (cwd or Path.cwd()) / _STAGE_DIR
        directory.mkdir(parents=True, exist_ok=True)
        (directory / _STAGE_FILE).write_text(json.dumps(asdict(self), indent=2))
