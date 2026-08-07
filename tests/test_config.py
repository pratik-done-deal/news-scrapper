"""The config module that replaced `.env`.

What matters here is the precedence rule — a flag the caller actually passed
wins, anything they left off keeps the default in `src/config.py` — and that
the config survives the trip to a child process, since spawned scrape workers
and uvicorn's reloader never run the parser themselves.
"""
import argparse
import json
import os

import pytest

from src.config import (
    CONFIG_ENV_VAR,
    AppConfig,
    ConfigError,
    add_config_arguments,
    boolean,
    get_config,
    load_config,
    reset_config,
    set_config,
)


@pytest.fixture(autouse=True)
def clean_config():
    reset_config()
    yield
    reset_config()


def parse(argv: list[str], only=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    add_config_arguments(parser, only=only)
    return parser.parse_args(argv)


def test_defaults_apply_when_nothing_is_passed():
    config = load_config(parse([]))

    assert config.neo4j.uri == "neo4j://127.0.0.1:7687"
    assert config.api.port == 8000
    assert config.auth.enabled is True
    assert config.logging.level == "INFO"


def test_parser_values_overwrite_the_defaults():
    config = load_config(parse([
        "--neo4j-uri", "neo4j://db:7687",
        "--neo4j-password", "s3cret",
        "--api-port", "9000",
        "--auth-enabled", "false",
        "--auth-timeout-seconds", "2.5",
        "--cors-allowed-origins", "https://a.test, https://b.test",
    ]))

    assert config.neo4j.uri == "neo4j://db:7687"
    assert config.neo4j.password == "s3cret"
    assert config.api.port == 9000
    assert config.auth.enabled is False
    assert config.auth.timeout_seconds == 2.5
    assert config.api.cors_allowed_origins == ["https://a.test", "https://b.test"]
    # Untouched sections keep their defaults.
    assert config.neo4j.user == "neo4j"


def test_only_narrows_the_flags_an_entry_point_offers():
    args = parse(["--neo4j-uri", "neo4j://db:7687"], only=("neo4j", "groq"))
    assert not hasattr(args, "api_port")

    parser = argparse.ArgumentParser()
    add_config_arguments(parser, only=("neo4j",))
    with pytest.raises(SystemExit):
        parser.parse_args(["--api-port", "9000"])


def test_boolean_rejects_anything_ambiguous():
    assert boolean("TRUE") is True
    assert boolean("off") is False
    with pytest.raises(argparse.ArgumentTypeError):
        boolean("maybe")


def test_secrets_are_empty_until_passed():
    """The tracked defaults hold no credentials, and a missing one is loud."""
    config = load_config(parse([]))

    with pytest.raises(ConfigError):
        config.require_neo4j_password()
    with pytest.raises(ConfigError):
        config.require_groq_api_key()

    config.groq.api_key = "gsk_test"
    assert config.require_groq_api_key() == "gsk_test"


def test_the_resolved_config_reaches_a_child_process():
    """A spawned worker re-derives the parent's config, not the defaults."""
    load_config(parse(["--log-level", "DEBUG", "--neo4j-password", "s3cret"]))

    exported = json.loads(os.environ[CONFIG_ENV_VAR])
    assert exported["logging"]["level"] == "DEBUG"

    # What a fresh interpreter does: no parser has run, only the environment.
    reset_config_but_keep_export = os.environ[CONFIG_ENV_VAR]
    reset_config()
    os.environ[CONFIG_ENV_VAR] = reset_config_but_keep_export

    assert get_config().logging.level == "DEBUG"
    assert get_config().neo4j.password == "s3cret"


def test_an_unreadable_export_falls_back_to_defaults():
    """A worker is not worth failing over a corrupt blob; defaults still run."""
    os.environ[CONFIG_ENV_VAR] = "{not json"
    assert get_config().api.port == 8000


def test_unknown_keys_in_an_export_are_ignored():
    """The blob may come from a parent running slightly different code."""
    config = AppConfig.from_dict({"neo4j": {"uri": "neo4j://db:7687", "future": 1}})
    assert config.neo4j.uri == "neo4j://db:7687"


def test_get_config_returns_what_was_installed():
    installed = set_config(AppConfig())
    installed.api.port = 1234
    assert get_config() is installed
