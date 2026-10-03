"""Publish staged export files with ownership checks and handled-failure rollback.

SQLite and a filesystem are not one atomic store. The caller commits its database
transaction in the final callback. Abrupt process termination can leave a lock
and recovery backup; this helper never claims crash-atomic publication.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path, PurePosixPath, PureWindowsPath

from ..config import ConfigError
from ..naming import normalize_category_path

_OWNER = ".mboxer-notebooklm.json"


def _owner_identity(root: Path) -> dict[str, object]:
    return {"tool_name": "mboxer", "export_kind": "notebooklm",
            "account_key": root.name, "version": 1}


class ExportPublicationError(ConfigError):
    """Output ownership or publication could not be established safely."""


def _relative(value: str) -> Path:
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or PureWindowsPath(value).drive
            or "\\" in value or any(part in {"", ".", ".."} for part in value.split("/"))):
        raise ExportPublicationError("Export inventory contains an unsafe relative path.")
    return Path(*path.parts)


def _digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _target(root: Path, name: str) -> Path:
    target = root / _relative(name)
    current = root
    for part in target.relative_to(root).parts:
        current /= part
        if current.is_symlink():
            raise ExportPublicationError("Export destination contains a symlink.")
        if current != target and current.exists() and not current.is_dir():
            raise ExportPublicationError("Export destination parent is not a directory.")
    if target.exists() and not target.is_file():
        raise ExportPublicationError("Export destination collides with a directory.")
    return target


def _notebooklm_inventory(root: Path) -> dict[str, str]:
    marker = _target(root, _OWNER)
    if marker.exists():
        try:
            valid = json.loads(marker.read_text(encoding="utf-8")) == _owner_identity(root)
        except (OSError, ValueError):
            valid = False
        if not valid:
            raise ExportPublicationError("Existing NotebookLM ownership marker is invalid.")
    manifest = _target(root, "manifest.json")
    if not manifest.exists():
        # A CSV without the authoritative JSON inventory cannot authorize deletion.
        if _target(root, "manifest.csv").exists() or marker.exists():
            raise ExportPublicationError("Existing CSV manifest has no JSON ownership inventory.")
        return {}
    try:
        rows = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ExportPublicationError("Existing export manifest cannot establish file ownership.") from exc
    if not isinstance(rows, list):
        raise ExportPublicationError("Existing export manifest must contain a list of files.")
    if not rows and not marker.exists():
        raise ExportPublicationError(
            "An empty legacy manifest cannot establish ownership. Select a new destination "
            "or manually review and move the old export first."
        )
    owned: dict[str, str] = {"manifest.json": _digest(manifest)}
    if marker.exists():
        owned[_OWNER] = _digest(marker)
    csv_manifest = _target(root, "manifest.csv")
    if csv_manifest.exists():
        owned["manifest.csv"] = _digest(csv_manifest)
    for row in rows:
        if (not isinstance(row, dict) or row.get("tool_name") != "mboxer"
                or row.get("export_kind") != "notebooklm"
                or row.get("account_key") != root.name):
            raise ExportPublicationError("Existing manifest is not this account's NotebookLM export.")
        category = row.get("category_path")
        band = row.get("date_band")
        filename = row.get("generated_file")
        digest = row.get("generated_sha256")
        if (not isinstance(category, str) or not isinstance(band, str)
                or not isinstance(filename, str) or not isinstance(digest, str)):
            raise ExportPublicationError("Existing export manifest contains invalid ownership fields.")
        if (not re.fullmatch(r"[0-9a-f]{64}", digest)
                or normalize_category_path(category) != category
                or "/" in band or "/" in filename):
            raise ExportPublicationError("Existing export manifest contains invalid ownership fields.")
        name = _relative(f"{category}/{band}/{filename}").as_posix()
        if name in owned:
            raise ExportPublicationError("Existing export manifest contains duplicate output paths.")
        owned[name] = digest
    return owned


def _publish(
    root: Path,
    files: dict[str, Path],
    commit: Callable[[], None],
    *,
    notebooklm: bool,
) -> None:
    root = root.absolute()
    if any(item.is_symlink() for item in (root, *root.parents)):
        raise ExportPublicationError("Export destination must not be a symlink.")
    root = root.parent.resolve() / root.name
    if root.exists() and not root.is_dir():
        raise ExportPublicationError("Export destination must be a directory.")
    root.parent.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(str(root).encode()).hexdigest()[:20]
    lock = root.parent / f".mboxer-export-{key}.lock"
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ExportPublicationError(
            "Export destination is locked by another publication or an interrupted run. "
            "Inspect recovery backups before clearing a stale lock."
        ) from exc
    backup: Path | None = None
    keep_lock = False
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(f"pid={os.getpid()}\n")
        files = dict(files)
        backup = Path(tempfile.mkdtemp(prefix=".mboxer-backup-", dir=root.parent))
        if notebooklm:
            if _OWNER in files:
                raise ExportPublicationError("Export staging uses a reserved ownership filename.")
            marker = backup / "owner.json"
            marker.write_text(json.dumps(_owner_identity(root)) + "\n", encoding="utf-8")
            files[_OWNER] = marker
        targets = {name: _target(root, name) for name in files}
        if len({name.casefold() for name in targets}) != len(targets):
            raise ExportPublicationError("Export paths collide on a case-insensitive filesystem.")
        for name, source in files.items():
            if source.is_symlink() or not source.is_file() or source.resolve() == targets[name].resolve():
                raise ExportPublicationError("Export staging file is missing or invalid.")
        owned = _notebooklm_inventory(root) if notebooklm else {}
        for name, digest in owned.items():
            target = _target(root, name)
            if target.exists() and _digest(target) != digest:
                raise ExportPublicationError(
                    "A previously generated export was modified; preserve it or select a new destination."
                )
        if notebooklm:
            for name, target in targets.items():
                if target.exists() and name not in owned:
                    raise ExportPublicationError("Export would overwrite an unrelated file.")
        obsolete = set(owned) - set(targets) if notebooklm else set()
        touched = {name: _target(root, name) for name in set(targets) | obsolete}
        # Copy before touching live output. Staging may be on another filesystem.
        ready: dict[str, Path] = {}
        for index, (name, source) in enumerate(sorted(files.items())):
            destination = backup / f"install-{index}"
            shutil.copyfile(source, destination)
            destination.chmod(0o600)
            ready[name] = destination
        (backup / "recovery.json").write_text(json.dumps({
            "destination": str(root), "install": sorted(targets),
            "previous": [name for name, target in sorted(touched.items()) if target.exists()],
            "instructions": "Previous files are under previous/ with their original relative paths. "
            "Inspect the destination and database before manual recovery; do not blindly replay.",
        }, indent=2) + "\n", encoding="utf-8")
        moved: dict[Path, Path] = {}
        installed: list[Path] = []
        created_dirs: list[Path] = []

        def ensure_directory(directory: Path) -> None:
            missing = []
            while not directory.exists():
                missing.append(directory)
                directory = directory.parent
            for item in reversed(missing):
                item.mkdir()
                created_dirs.append(item)

        try:
            for name, target in sorted(touched.items()):
                if target.exists():
                    saved = backup / "previous" / name
                    saved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    os.replace(target, saved)
                    moved[target] = saved
            for name, target in sorted(targets.items()):
                ensure_directory(target.parent)
                os.replace(ready[name], target)
                installed.append(target)
            commit()
        except BaseException as original:
            try:
                for target in reversed(installed):
                    target.unlink(missing_ok=True)
                for target, saved in moved.items():
                    os.replace(saved, target)
                for directory in reversed(created_dirs):
                    directory.rmdir()
            except BaseException as recovery:
                # Do not erase the only remaining copy of previous output.
                saved_backup = backup
                backup = None
                keep_lock = True
                raise ExportPublicationError(
                    f"Publication recovery failed; previous files are retained in {saved_backup}."
                ) from recovery
            if not isinstance(original, Exception):
                raise
            raise ExportPublicationError("Publication failed; previous output files were restored.") from original
        # Remove empty stale category directories; never remove unrelated files.
        for name in sorted(obsolete, reverse=True):
            directory = (root / name).parent
            while directory != root:
                try:
                    directory.rmdir()
                except OSError:
                    break
                directory = directory.parent
    finally:
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)
        # Cleanup must not turn a committed publication into a reported failure.
        if not keep_lock:
            with suppress(OSError):
                lock.unlink(missing_ok=True)


def publish_files(root: Path, files: dict[str, Path], *, commit: Callable[[], None]) -> None:
    """Replace an explicit file set, restoring prior files on handled failures."""
    _publish(root, files, commit, notebooklm=False)


def publish_notebooklm(root: Path, files: dict[str, Path], *, commit: Callable[[], None]) -> None:
    """Replace this account's managed generation, removing obsolete owned packs."""
    _publish(root, files, commit, notebooklm=True)
