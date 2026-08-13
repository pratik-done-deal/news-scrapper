"""Application configuration — the replacement for the old `.env` file.

Every deployment value the service needs lives here as a dataclass field with
a working default, and every one of them is overridable from the command line:
`add_config_arguments` puts the flags on an entry point's parser, and
`load_config(args)` lays whatever the caller actually passed over the defaults.
Nothing reads `.env` any more.

Secrets (`--neo4j-password`, `--gemini-api-key`, `--mysql-password`) default to
empty on purpose. This file is tracked by git, so a real credential has to
arrive on the command line, and a process that needs one it was not given
fails loudly at startup rather than half-working.

The resolved config is installed process-wide (`get_config`) and exported to
the environment as a single JSON blob under NEWS_SCRAPPER_CONFIG. That export
is an internal transport, not a configuration surface: `spawn`ed scrape workers
and uvicorn's reloader start a fresh interpreter that never ran the parser, and
without it they would silently fall back to these defaults.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional, Sequence

CONFIG_ENV_VAR = "NEWS_SCRAPPER_CONFIG"

_TRUTHY = {"1", "true", "yes", "on"}
_FALSEY = {"0", "false", "no", "off"}

DEFAULT_VALIDATE_PATH = "/api/company-service/v1/internal/token/validate"
DEFAULT_LOG_FILE = "news_agent.log"


class ConfigError(RuntimeError):
    """A required setting is missing or unusable."""


def boolean(value: str) -> bool:
    """argparse `type` for explicit --flag true/false values.

    A store_true flag cannot express "leave the default alone", and every
    override here has to be distinguishable from an absent one.
    """
    text = str(value).strip().lower()
    if text in _TRUTHY:
        return True
    if text in _FALSEY:
        return False
    raise argparse.ArgumentTypeError(f"expected true or false, got {value!r}")


def csv_list(value: str) -> list[str]:
    return [item.strip() for item in str(value).split(",") if item.strip()]


@dataclass
class Neo4jSettings:
    uri: str = "neo4j://127.0.0.1:7687"
    user: str = "neo4j"
    password: str = ""
    database: str = "newsscrapedatabase"


@dataclass
class GroqSettings:
    """The LLM API key — a Gemini key, passed as `--gemini-api-key`.

    The section keeps the `groq` name because it is the key in the exported
    NEWS_SCRAPPER_CONFIG blob and in `config/settings.yaml`; renaming it would
    strand every already-exported blob. The CLI flag has been renamed, with
    `--groq-api-key` kept as an alias."""

    api_key: str = ""


@dataclass
class AuthSettings:
    """Session validation against the Done Deal company-service.

    `enabled = False` serves every endpoint unauthenticated and is for local
    development only; it logs a warning on every startup.
    """

    enabled: bool = True
    service_base_url: str = "https://qa.done.deals"
    validate_path: str = DEFAULT_VALIDATE_PATH
    timeout_seconds: float = 5.0
    # 0 validates on every request; a revoked session stays usable this long.
    cache_ttl_seconds: float = 30.0
    # True only behind a proxy we control, which sets X-Forwarded-For itself.
    trust_proxy_headers: bool = False
    # Who owns the bookmarks written while `enabled = False`. There is no
    # session to identify the caller then, so everything lands on this one id —
    # which is why it is only ever reached with auth off. With auth on, a
    # session that carries no userId is refused rather than pooled here.
    dev_user_id: int = 0


@dataclass
class ApiSettings:
    """The HTTP layer and the timers that run inside it.

    The scheduler is in-process and holds no cross-process lock, so it is off
    by default: at most one instance may pass `--scheduler-enabled true`, and
    every other API replica must leave it off or all work is duplicated.
    """

    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = False  # dev only — never true in production
    # Browser origins the API answers with CORS headers for. `allow_credentials`
    # is on, so "*" is not usable and every origin has to be named. An origin is
    # scheme + host + port and nothing else: no trailing slash, and http and
    # https are two different entries.
    cors_allowed_origins: list[str] = field(
        default_factory=lambda: [
            "https://app.done.deals",
            "https://qa.done.deals",
            "http://localhost:3000",
        ]
    )
    scheduler_enabled: bool = True


@dataclass
class MySQLSettings:
    """Company MySQL (read-only). Unset host/database runs without it.

    `password` is Optional rather than "" because an empty password is valid —
    local dev servers commonly have one — and "not given" has to stay
    distinguishable from "given as blank". `port` is Optional for the same
    reason: unset falls through to `company_mysql.port` in
    `config/settings.yaml`, which is where the tuning defaults live.
    """

    host: str = ""
    port: Optional[int] = None
    user: str = ""
    password: Optional[str] = None
    database: str = ""

    def is_configured(self) -> bool:
        """The minimum to attempt a connection at all."""
        return bool(self.host and self.database)


@dataclass
class LoggingSettings:
    level: str = "INFO"
    # Relative to the repo root; "none" for stdout only.
    file: str = DEFAULT_LOG_FILE
    max_bytes: int = 50 * 1024 * 1024
    backup_count: int = 5


@dataclass
class AppConfig:
    neo4j: Neo4jSettings = field(default_factory=Neo4jSettings)
    groq: GroqSettings = field(default_factory=GroqSettings)
    auth: AuthSettings = field(default_factory=AuthSettings)
    api: ApiSettings = field(default_factory=ApiSettings)
    mysql: MySQLSettings = field(default_factory=MySQLSettings)
    logging: LoggingSettings = field(default_factory=LoggingSettings)

    def require_neo4j_password(self) -> str:
        if not self.neo4j.password:
            raise ConfigError(
                "Neo4j password is not set. Pass --neo4j-password, or change the "
                "default in src/config.py."
            )
        return self.neo4j.password

    def require_groq_api_key(self) -> str:
        if not self.groq.api_key:
            raise ConfigError(
                "Gemini API key is not set. Pass --gemini-api-key, or change the "
                "default in src/config.py."
            )
        return self.groq.api_key

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict) -> "AppConfig":
        """Rebuild from `to_dict`, ignoring keys this version does not know.

        Tolerant on purpose: the JSON may have been written by a parent process
        running slightly different code, and an unknown key is not a reason to
        refuse to start.
        """
        sections = {
            "neo4j": Neo4jSettings,
            "groq": GroqSettings,
            "auth": AuthSettings,
            "api": ApiSettings,
            "mysql": MySQLSettings,
            "logging": LoggingSettings,
        }
        kwargs = {}
        for name, section_cls in sections.items():
            values = data.get(name) or {}
            known = {f.name for f in section_cls.__dataclass_fields__.values()}
            kwargs[name] = section_cls(
                **{k: v for k, v in values.items() if k in known}
            )
        return cls(**kwargs)


@dataclass(frozen=True)
class _Option:
    """One CLI flag and the config field it overrides."""

    flag: str
    section: str
    attr: str
    type: Callable[[str], Any]
    help: str
    metavar: Optional[str] = None
    # Older spellings of `flag` that still work. argparse maps them onto the
    # same dest, so a rename costs no deployment a redeploy.
    aliases: tuple[str, ...] = ()

    @property
    def dest(self) -> str:
        return self.flag.lstrip("-").replace("-", "_")


_BOOL_META = "{true,false}"

# The single source of truth for the CLI: the parser and the override pass are
# both generated from this, so a new setting cannot be added to one and
# forgotten in the other.
OPTIONS: tuple[_Option, ...] = (
    _Option("--neo4j-uri", "neo4j", "uri", str, "Neo4j bolt URI"),
    _Option("--neo4j-user", "neo4j", "user", str, "Neo4j user"),
    _Option("--neo4j-password", "neo4j", "password", str, "Neo4j password (required)"),
    _Option("--neo4j-database", "neo4j", "database", str, "Neo4j database name"),
    _Option(
        "--gemini-api-key", "groq", "api_key", str,
        "Gemini API key (required); --groq-api-key is a deprecated alias",
        aliases=("--groq-api-key",),
    ),
    _Option(
        "--auth-enabled", "auth", "enabled", boolean,
        "false serves every endpoint unauthenticated; local development only",
        _BOOL_META,
    ),
    _Option("--auth-base-url", "auth", "service_base_url", str, "company-service base URL"),
    _Option("--auth-validate-path", "auth", "validate_path", str, "Token validation path"),
    _Option("--auth-timeout-seconds", "auth", "timeout_seconds", float, "Validation request timeout"),
    _Option(
        "--auth-cache-ttl-seconds", "auth", "cache_ttl_seconds", float,
        "How long a validated session is cached; 0 validates every request",
    ),
    _Option(
        "--auth-trust-proxy-headers", "auth", "trust_proxy_headers", boolean,
        "Read the client IP from X-Forwarded-For", _BOOL_META,
    ),
    _Option(
        "--auth-dev-user-id", "auth", "dev_user_id", int,
        "User id that owns bookmarks made while --auth-enabled is false",
    ),
    _Option("--api-host", "api", "host", str, "Bind address for the API"),
    _Option("--api-port", "api", "port", int, "Bind port for the API"),
    _Option("--api-reload", "api", "reload", boolean, "Auto-reload on code changes (dev only)", _BOOL_META),
    _Option(
        "--cors-allowed-origins", "api", "cors_allowed_origins", csv_list,
        "Comma-separated list of allowed origins", "ORIGINS",
    ),
    _Option(
        "--scheduler-enabled", "api", "scheduler_enabled", boolean,
        "Run the scrape/extraction timers in this process; off by default, true on at most one instance",
        _BOOL_META,
    ),
    _Option("--mysql-host", "mysql", "host", str, "Company MySQL host"),
    _Option("--mysql-port", "mysql", "port", int, "Company MySQL port"),
    _Option("--mysql-user", "mysql", "user", str, "Company MySQL user"),
    _Option("--mysql-password", "mysql", "password", str, "Company MySQL password (may be empty)"),
    _Option("--mysql-database", "mysql", "database", str, "Company MySQL database"),
    _Option("--log-level", "logging", "level", str, "Root log level"),
    _Option("--log-file", "logging", "file", str, "Log file path, or 'none' for stdout only"),
    _Option("--log-max-bytes", "logging", "max_bytes", int, "Rotation threshold in bytes"),
    _Option("--log-backup-count", "logging", "backup_count", int, "Rotated files kept"),
)


def add_config_arguments(
    parser: argparse.ArgumentParser,
    only: Optional[Sequence[str]] = None,
) -> argparse.ArgumentParser:
    """Add the config override flags to an entry point's parser.

    Every flag defaults to None so "not passed" stays distinct from "passed
    the same value as the default" — only what the caller actually typed
    overrides `src/config.py`.

    `only` narrows the set to the given sections, for entry points that have no
    use for the rest (a CLI script does not serve HTTP).
    """
    group = parser.add_argument_group(
        "configuration overrides",
        "Defaults live in src/config.py; anything passed here wins over them.",
    )
    for option in OPTIONS:
        if only is not None and option.section not in only:
            continue
        group.add_argument(
            option.flag,
            *option.aliases,
            dest=option.dest,
            type=option.type,
            default=None,
            metavar=option.metavar,
            help=option.help,
        )
    return parser


def apply_overrides(config: AppConfig, args: argparse.Namespace) -> AppConfig:
    """Write every override the caller passed onto `config`, in place."""
    for option in OPTIONS:
        value = getattr(args, option.dest, None)
        if value is None:
            continue
        setattr(getattr(config, option.section), option.attr, value)
    return config


_installed: Optional[AppConfig] = None


def set_config(config: AppConfig, export: bool = True) -> AppConfig:
    """Install `config` as this process's configuration.

    `export` also writes it to the environment so child processes — spawned
    scrape workers, uvicorn's reloader — resolve the same values instead of
    silently reverting to the defaults.
    """
    global _installed
    _installed = config
    if export:
        os.environ[CONFIG_ENV_VAR] = config.to_json()
    return config


def load_config(args: Optional[argparse.Namespace] = None) -> AppConfig:
    """Defaults, overridden by the parser's values, installed process-wide."""
    config = AppConfig()
    if args is not None:
        apply_overrides(config, args)
    return set_config(config)


def get_config() -> AppConfig:
    """This process's configuration.

    Falls back to what a parent process exported, then to the defaults, so a
    module that is imported by a worker or a test still has a usable config
    without an entry point having run.
    """
    global _installed
    if _installed is None:
        _installed = _from_environment() or AppConfig()
    return _installed


def reset_config() -> None:
    """Drop the installed config, including the exported copy. For tests."""
    global _installed
    _installed = None
    os.environ.pop(CONFIG_ENV_VAR, None)


def _from_environment() -> Optional[AppConfig]:
    raw = os.environ.get(CONFIG_ENV_VAR)
    if not raw:
        return None
    try:
        return AppConfig.from_dict(json.loads(raw))
    except (ValueError, TypeError):
        # A corrupt blob is not worth failing a worker over; the defaults are
        # a working configuration and the parent already logged its own setup.
        return None
