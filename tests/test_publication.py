"""Publication ownership and filesystem/database failure boundaries."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mboxer.exporters import publication
from mboxer.exporters.publication import ExportPublicationError, publish_files, publish_notebooklm


def staged(tmp_path, contents):
    directory = tmp_path / "staging"
    directory.mkdir(exist_ok=True)
    result = {}
    for number, (name, content) in enumerate(contents.items()):
        path = directory / str(number)
        path.write_text(content)
        result[name] = path
    return result


def generation(root, body="old"):
    name = "general/2024/general-2024-001.md"
    content = {
        name: body,
        "manifest.json": json.dumps([{
            "tool_name": "mboxer", "export_kind": "notebooklm", "account_key": root.name,
            "category_path": "general", "date_band": "2024",
            "generated_file": "general-2024-001.md",
            "generated_sha256": hashlib.sha256(body.encode()).hexdigest(),
        }]),
        "manifest.csv": "synthetic manifest\n",
    }
    for name, value in content.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
    return content


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_empty_generation_removes_only_owned_files_and_can_be_republished(tmp_path):
    root = tmp_path / "account"
    generation(root)
    (root / "notes.txt").write_text("unrelated")
    for _ in range(2):
        files = staged(tmp_path, {"manifest.json": "[]", "manifest.csv": "new"})
        publish_notebooklm(root, files, commit=lambda: None)
        assert not list(root.rglob("*.md"))
        assert (root / "notes.txt").read_text() == "unrelated"
        assert json.loads((root / ".mboxer-notebooklm.json").read_text())["account_key"] == "account"


@pytest.mark.parametrize("failure", ["install", "commit", "copy"])
def test_failed_publication_restores_generation_and_stale_files(tmp_path, monkeypatch, failure):
    root = tmp_path / "account"
    generation(root)
    (root / "notes.txt").write_text("unrelated")
    before = snapshot(root)
    files = staged(tmp_path, {"manifest.json": "[]", "manifest.csv": "new"})
    replace = publication.os.replace

    def fail_install(source, target):
        if Path(source).name.startswith("install-") and Path(target).name == "manifest.json":
            raise OSError("synthetic install failure")
        replace(source, target)

    def fail(*args):
        raise OSError("synthetic failure")

    if failure == "install":
        monkeypatch.setattr(publication.os, "replace", fail_install)
    if failure == "copy":
        monkeypatch.setattr(publication.shutil, "copyfile", fail)
    expected = OSError if failure == "copy" else ExportPublicationError
    with pytest.raises(expected):
        publish_notebooklm(root, files, commit=fail if failure == "commit" else lambda: None)
    assert snapshot(root) == before
    assert not list(tmp_path.glob(".mboxer-*"))


def test_rollback_failure_keeps_recoverable_paths_and_lock(tmp_path, monkeypatch):
    root = tmp_path / "account"
    generation(root)
    files = staged(tmp_path, {"manifest.json": "[]", "manifest.csv": "new"})
    replace = publication.os.replace

    def fail_restore(source, target):
        if "previous" in Path(source).parts:
            raise OSError("synthetic restore failure")
        replace(source, target)

    def fail_commit():
        raise OSError("synthetic commit failure")

    monkeypatch.setattr(publication.os, "replace", fail_restore)
    with pytest.raises(ExportPublicationError, match="recovery failed"):
        publish_notebooklm(root, files, commit=fail_commit)
    backup, = tmp_path.glob(".mboxer-backup-*")
    assert (backup / "previous/general/2024/general-2024-001.md").read_text() == "old"
    assert json.loads((backup / "recovery.json").read_text())["destination"] == str(root)
    with pytest.raises(ExportPublicationError, match="locked"):
        publish_notebooklm(root, files, commit=lambda: None)


@pytest.mark.parametrize("scenario", ["modified", "unowned", "empty", "invalid", "traversal", "foreign"])
def test_untrusted_ownership_is_refused_without_changes(tmp_path, scenario):
    root = tmp_path / "account"
    generation(root)
    if scenario == "modified":
        next(root.rglob("*.md")).write_text("user edited")
    elif scenario == "unowned":
        (root / "collision.md").write_text("unrelated")
    elif scenario == "empty":
        (root / "manifest.json").write_text("[]")
    elif scenario == "invalid":
        (root / "manifest.json").write_text("{")
    else:
        rows = json.loads((root / "manifest.json").read_text())
        rows[0]["date_band" if scenario == "traversal" else "account_key"] = ".." if scenario == "traversal" else "another"
        (root / "manifest.json").write_text(json.dumps(rows))
    before = snapshot(root)
    files = staged(tmp_path, {"manifest.json": "[]", "manifest.csv": "new", "collision.md": "new"})
    with pytest.raises(ExportPublicationError):
        publish_notebooklm(root, files, commit=lambda: pytest.fail("must not commit"))
    assert snapshot(root) == before


@pytest.mark.parametrize("name", ["../outside", "/absolute", "a/../outside", "C:/outside", "a\\outside", "a//b"])
def test_unsafe_target_names_are_refused(tmp_path, name):
    files = staged(tmp_path, {name: "new"})
    with pytest.raises(ExportPublicationError, match="unsafe"):
        publish_files(tmp_path / "out", files, commit=lambda: None)


@pytest.mark.parametrize("ancestor", [False, True])
def test_symlink_destination_is_refused(tmp_path, ancestor):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    files = staged(tmp_path, {"data.jsonl": "new"})
    with pytest.raises(ExportPublicationError, match="symlink"):
        publish_files(link / "child" if ancestor else link, files, commit=lambda: None)
    assert not list(real.iterdir())


def test_install_uses_same_filesystem_staging(tmp_path, monkeypatch):
    root = tmp_path / "out"
    files = staged(tmp_path, {"data.jsonl": "new", "data.manifest.json": "[]"})
    replace = publication.os.replace

    def enforce_local_source(source, target):
        assert Path(source).parent.name.startswith(".mboxer-backup-")
        assert Path(source).parent.parent == root.parent
        replace(source, target)

    monkeypatch.setattr(publication.os, "replace", enforce_local_source)
    publish_files(root, files, commit=lambda: None)
    assert (root / "data.jsonl").read_text() == "new"


def test_cleanup_failure_does_not_report_committed_export_as_failed(tmp_path, monkeypatch):
    files = staged(tmp_path, {"data.jsonl": "new"})
    committed = []
    monkeypatch.setattr(publication.shutil, "rmtree", lambda *args, **kwargs: None)
    publish_files(tmp_path / "out", files, commit=lambda: committed.append(True))
    assert committed == [True]
    assert (tmp_path / "out/data.jsonl").read_text() == "new"
