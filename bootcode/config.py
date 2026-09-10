"""Reads/writes ``~/.config/bootcode/config.toml``.

Field names (``cli_token``/``api_url``) intentionally match the old Go CLI's
config so the two never diverge in spirit, even though this is a fresh
implementation.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

import tomli_w

# The old (pre-rewrite) bootcode was frontend/backend-split, hence a
# separate `api.` subdomain -- today bootcode-app is a single Next.js app
# (one Vercel deployment) serving both the API and the web pages from the
# same `bootcode.cn` domain, so both defaults are deliberately identical.
# Kept as two separate Config fields anyway (matching the old Go CLI's
# config.go APIURL/FrontendURL split) since a future re-split isn't ruled out.
DEFAULT_API_URL = "https://bootcode.cn"
DEFAULT_FRONTEND_URL = "https://bootcode.cn"


def _config_dir() -> Path:
    override = os.environ.get("BOOTCODE_CONFIG_DIR")
    return Path(override) if override else Path.home() / ".config" / "bootcode"


def _config_path() -> Path:
    return _config_dir() / "config.toml"


@dataclass
class Config:
    cli_token: str = ""
    api_url: str = DEFAULT_API_URL
    frontend_url: str = DEFAULT_FRONTEND_URL

    @classmethod
    def load(cls) -> "Config":
        path = _config_path()
        if not path.exists():
            return cls()
        data = tomllib.loads(path.read_text())
        return cls(
            cli_token=data.get("cli_token", ""),
            api_url=data.get("api_url", DEFAULT_API_URL),
            frontend_url=data.get("frontend_url", DEFAULT_FRONTEND_URL),
        )

    def save(self) -> None:
        _config_dir().mkdir(parents=True, exist_ok=True)
        path = _config_path()
        path.write_text(tomli_w.dumps(asdict(self)))
        # cli_token is a bearer credential stored in plaintext -- restrict
        # to owner-only, mirroring the archived Go CLI's configFilePerm
        # (0600). write_text() doesn't respect umask for this, so it must
        # be set explicitly, and re-applied on every save in case an
        # earlier version of the file predates this fix.
        path.chmod(0o600)
