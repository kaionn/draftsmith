#!/usr/bin/env python3
"""Safe, private storage below the current worktree's Git metadata directory."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any


class StorageError(RuntimeError):
    pass


def run_git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], check=False, capture_output=True, text=True
    )
    if proc.returncode != 0:
        message = proc.stderr.strip() or proc.stdout.strip() or "git command failed"
        raise StorageError(message)
    return proc.stdout.strip()


def repository_root(repo_arg: str | Path) -> Path:
    repo = Path(repo_arg).expanduser().resolve()
    return Path(run_git(repo, "rev-parse", "--show-toplevel")).resolve()


def _reject_symlinks(path: Path, stop: Path) -> None:
    current = path
    while True:
        if current.exists() and current.is_symlink():
            raise StorageError(f"symlinked Git metadata path is not allowed: {current}")
        if current == stop:
            return
        if stop not in current.parents:
            raise StorageError("Git metadata path escapes the absolute Git directory")
        current = current.parent


def metadata_dir(repo_arg: str | Path, name: str, *, create: bool = False) -> Path:
    if not name or Path(name).is_absolute() or ".." in Path(name).parts:
        raise StorageError("metadata name must be a safe relative path")
    root = repository_root(repo_arg)
    git_dir_raw = Path(run_git(root, "rev-parse", "--absolute-git-dir"))
    if git_dir_raw.is_symlink():
        raise StorageError("symlinked absolute Git directory is not allowed")
    git_dir = git_dir_raw.resolve()
    raw = Path(run_git(root, "rev-parse", "--git-path", name))
    candidate = raw if raw.is_absolute() else root / raw
    _reject_symlinks(candidate.absolute(), git_dir)
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(git_dir)
    except ValueError as exc:
        raise StorageError("Git metadata output escapes the absolute Git directory") from exc
    if create:
        resolved.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(resolved, 0o700)
    return resolved


def atomic_json(path: Path, payload: dict[str, Any], *, immutable: bool = False) -> None:
    if immutable and path.exists():
        raise StorageError(f"immutable output already exists: {path.name}")
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(parent, 0o700)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=parent, prefix=f".{path.name}.", delete=False
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, 0o600)
        if immutable and path.exists():
            raise StorageError(f"immutable output already exists: {path.name}")
        os.replace(temp_path, path)
        os.chmod(path, 0o600)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def atomic_text(path: Path, content: str, *, immutable: bool = False) -> None:
    if immutable and path.exists():
        raise StorageError(f"immutable output already exists: {path.name}")
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(parent, 0o700)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=parent, prefix=f".{path.name}.", delete=False
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(content)
            if not content.endswith("\n"):
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, 0o600)
        if immutable and path.exists():
            raise StorageError(f"immutable output already exists: {path.name}")
        os.replace(temp_path, path)
        os.chmod(path, 0o600)
    finally:
        if temp_path.exists():
            temp_path.unlink()
