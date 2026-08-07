"""Project paths and config loading anchored to the repo root, not the cwd.

The API and the pipeline both read `config/*.yaml`. Resolving those against the
current working directory means the service only starts when it happens to be
launched from the repo root — but systemd, Docker and supervisors routinely set
a different cwd, and the failure shows up as a FileNotFoundError during
startup. Everything here is derived from this file's own location instead, so
the process starts from anywhere.

Deployment values (credentials, ports, log level) are not here: they live in
`src/config.py` and are overridden from the command line.
"""

from pathlib import Path
from typing import Union

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
SETTINGS_PATH = CONFIG_DIR / "settings.yaml"
SOURCES_PATH = CONFIG_DIR / "sources.yaml"


def load_yaml(path: Union[str, Path]) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def load_settings() -> dict:
    """`config/settings.yaml` — timeouts, Groq model, pool sizes, scheduler."""
    return load_yaml(SETTINGS_PATH)


def load_sources_config() -> dict:
    """`config/sources.yaml` in full — callers read the `sources` key off it."""
    return load_yaml(SOURCES_PATH)
