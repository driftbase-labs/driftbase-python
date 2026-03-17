"""
Git integration utilities for Driftbase.

Provides functions to detect git repository context and extract metadata.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class GitContext:
    """Git repository context information."""

    enabled: bool
    """Whether git integration is enabled and repository detected."""

    commit_sha: str | None
    """Current commit SHA (short form, 8 chars)."""

    branch: str | None
    """Current branch name."""

    is_dirty: bool
    """Whether there are uncommitted changes."""

    remote_url: str | None
    """Remote origin URL if available."""

    tag: str | None
    """Current tag if on a tagged commit."""


def is_git_repo(path: Path | None = None) -> bool:
    """Check if path is within a git repository."""
    if path is None:
        path = Path.cwd()

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=path,
            capture_output=True,
            timeout=2,
            check=False,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def get_git_context(path: Path | None = None) -> GitContext:
    """
    Get current git repository context.

    Returns GitContext with enabled=False if not in a git repo or git not available.
    """
    if path is None:
        path = Path.cwd()

    if not is_git_repo(path):
        return GitContext(
            enabled=False,
            commit_sha=None,
            branch=None,
            is_dirty=False,
            remote_url=None,
            tag=None,
        )

    try:
        # Get commit SHA
        sha_result = subprocess.run(
            ["git", "rev-parse", "--short=8", "HEAD"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        commit_sha = sha_result.stdout.strip() if sha_result.returncode == 0 else None

        # Get branch name
        branch_result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        branch = branch_result.stdout.strip() if branch_result.returncode == 0 else None
        if branch == "HEAD":
            branch = None  # Detached HEAD state

        # Check for uncommitted changes
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        is_dirty = (
            bool(status_result.stdout.strip())
            if status_result.returncode == 0
            else False
        )

        # Get remote URL
        remote_result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        remote_url = (
            remote_result.stdout.strip() if remote_result.returncode == 0 else None
        )

        # Get tag if on tagged commit
        tag_result = subprocess.run(
            ["git", "describe", "--exact-match", "--tags", "HEAD"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        tag = tag_result.stdout.strip() if tag_result.returncode == 0 else None

        return GitContext(
            enabled=True,
            commit_sha=commit_sha,
            branch=branch,
            is_dirty=is_dirty,
            remote_url=remote_url,
            tag=tag,
        )

    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        logger.debug(f"Failed to get git context: {e}")
        return GitContext(
            enabled=False,
            commit_sha=None,
            branch=None,
            is_dirty=False,
            remote_url=None,
            tag=None,
        )


def get_commit_sha_for_branch(branch: str, path: Path | None = None) -> str | None:
    """Get the commit SHA for a specific branch."""
    if path is None:
        path = Path.cwd()

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=8", branch],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def get_commits_between(base: str, head: str, path: Path | None = None) -> list[str]:
    """
    Get list of commit SHAs between base and head.

    Args:
        base: Base commit/branch
        head: Head commit/branch
        path: Repository path

    Returns:
        List of commit SHAs (short form)
    """
    if path is None:
        path = Path.cwd()

    try:
        result = subprocess.run(
            ["git", "rev-list", "--reverse", f"{base}..{head}"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            commits = result.stdout.strip().split("\n")
            # Get short SHAs
            short_commits = []
            for commit in commits:
                if commit:
                    short_result = subprocess.run(
                        ["git", "rev-parse", "--short=8", commit],
                        cwd=path,
                        capture_output=True,
                        text=True,
                        timeout=2,
                        check=False,
                    )
                    if short_result.returncode == 0:
                        short_commits.append(short_result.stdout.strip())
            return short_commits
        return []
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def format_git_label(ctx: GitContext) -> str:
    """
    Format git context as a human-readable label.

    Examples:
        "main@a1b2c3d4"
        "feature-branch@a1b2c3d4 (dirty)"
        "v1.2.3@a1b2c3d4"
    """
    if not ctx.enabled or not ctx.commit_sha:
        return "unknown"

    # Prefer tag over branch
    ref = ctx.tag or ctx.branch or "detached"
    label = f"{ref}@{ctx.commit_sha}"

    if ctx.is_dirty:
        label += " (dirty)"

    return label


def get_common_ancestor(
    branch1: str, branch2: str, path: Path | None = None
) -> str | None:
    """Get the common ancestor commit of two branches."""
    if path is None:
        path = Path.cwd()

    try:
        result = subprocess.run(
            ["git", "merge-base", branch1, branch2],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode == 0:
            full_sha = result.stdout.strip()
            # Get short SHA
            short_result = subprocess.run(
                ["git", "rev-parse", "--short=8", full_sha],
                cwd=path,
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            if short_result.returncode == 0:
                return short_result.stdout.strip()
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
