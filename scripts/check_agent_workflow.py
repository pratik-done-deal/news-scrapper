#!/usr/bin/env python3
"""Validate repo-local agent workflow docs."""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTEXT_ROOT = ROOT / "docs" / "agent-context"
SKILLS_ROOT = ROOT / ".agents" / "skills"

LAST_REFRESHED_RE = re.compile(r"^Last refreshed: (\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)
BACKTICK_REF_RE = re.compile(r"`([^`]+(?:\.md|\.toml|\.py|\.yaml|\.yml|\.ps1))`")

REQUIRED_CONTEXT_FILES = [
    "README.md",
    "task-routing.md",
    "codebase-map.md",
    "development-guidelines.md",
    "high-risk-files.md",
    "agent-workflow-cheatsheet.md",
]

REQUIRED_SKILLS = [
    "prd-analyzer",
    "feature-researcher",
    "dev-executor",
    "bug-solver",
    "code-reviewer",
    "python-verifier",
    "context-cache-maintainer",
    "task-orchestrator",
]


def resolve_reference(reference: str) -> Path | None:
    if reference.startswith(("http://", "https://")):
        return None
    if reference.startswith((".agents/", ".codex/", "docs/", "agents/", "skills/", "scripts/", "config/")):
        return ROOT / reference
    if reference.startswith("module-cache/"):
        return CONTEXT_ROOT / reference
    if reference.startswith("src/"):
        return ROOT / reference
    return None


def check_last_refreshed(path: Path, stale_after_days: int, errors: list[str], warnings: list[str]) -> None:
    if path.name == "README.md":
        return

    text = path.read_text(encoding="utf-8")
    match = LAST_REFRESHED_RE.search(text)
    if not match:
        errors.append(f"Missing 'Last refreshed: YYYY-MM-DD' in {path.relative_to(ROOT)}")
        return

    refreshed = dt.date.fromisoformat(match.group(1))
    age = (dt.date.today() - refreshed).days
    if age > stale_after_days:
        warnings.append(f"Stale cache date ({age} days old) in {path.relative_to(ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stale-after-days", type=int, default=30)
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []

    for rel in REQUIRED_CONTEXT_FILES:
        path = CONTEXT_ROOT / rel
        if not path.exists():
            errors.append(f"Missing context file: {path.relative_to(ROOT)}")

    for skill in REQUIRED_SKILLS:
        path = SKILLS_ROOT / skill / "SKILL.md"
        if not path.exists():
            errors.append(f"Missing skill file: {path.relative_to(ROOT)}")
            continue
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            errors.append(f"Missing frontmatter in {path.relative_to(ROOT)}")
        if f"name: {skill}" not in text:
            errors.append(f"Skill name mismatch or missing name in {path.relative_to(ROOT)}")

    if CONTEXT_ROOT.exists():
        for path in CONTEXT_ROOT.rglob("*.md"):
            check_last_refreshed(path, args.stale_after_days, errors, warnings)

            text = path.read_text(encoding="utf-8")
            for match in BACKTICK_REF_RE.finditer(text):
                reference = match.group(1)
                if "*" in reference or "<" in reference or ">" in reference:
                    continue
                resolved = resolve_reference(reference)
                if resolved is not None and not resolved.exists():
                    errors.append(
                        f"{path.relative_to(ROOT)} references missing file '{reference}'"
                    )

    workflow_router = ROOT / ".codex" / "agents" / "workflow-router.toml"
    if not workflow_router.exists():
        errors.append("Missing .codex/agents/workflow-router.toml")

    for warning in warnings:
        print(f"WARN: {warning}")

    if errors:
        print("Agent workflow check failed:")
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print("Agent workflow check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
