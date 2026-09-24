"""D8.3 recovery primitives for installed Stygnox transactions.

The module deliberately contains no legacy Ralph imports.  Clean/new recovery
uses a controller-owned pre-authority checkpoint created only after explicit
handoff confirmation.  Dirty recovery never copies the operator baseline into
controller custody: it verifies and consumes the independently owned capture
referenced by the D8.2 attestation.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tarfile
import tempfile
from typing import Any


RUNTIME_NAME = ".stygnox"
INTERNAL_RECOVERY_DIR = "recovery"
INTERNAL_METADATA = "pre-authority.json"
INTERNAL_ARCHIVE = "pre-authority.tar"
INTERNAL_INDEX = "pre-authority.index"
INTERNAL_SCHEMA = "stygnox_internal_recovery_v1"
OPERATOR_MANIFEST_SCHEMA = "stygnox_operator_recovery_manifest_v1"
LOCAL_EXCLUDE_MARKER = "# Stygnox retained controller runtime after recovery"
LOCAL_EXCLUDE_PATTERN = "/.stygnox/"


class RecoveryError(RuntimeError):
    """Fail-closed recovery error."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(root: Path, *args: str, check: bool = True, env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    if env:
        environment.update({str(key): str(value) for key, value in env.items()})
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        env=environment,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise RecoveryError(
            f"git {' '.join(args)} failed ({result.returncode}): "
            f"{(result.stderr or result.stdout).decode('utf-8', errors='replace').strip()}"
        )
    return result


def _record(path: Path, relative: str) -> dict[str, str]:
    info = path.lstat()
    mode = f"{stat.S_IMODE(info.st_mode):04o}"
    if stat.S_ISDIR(info.st_mode):
        return {"path": relative, "type": "dir", "mode": mode, "sha256": ""}
    if stat.S_ISLNK(info.st_mode):
        return {
            "path": relative,
            "type": "symlink",
            "mode": mode,
            "sha256": sha256_bytes(os.readlink(path).encode("utf-8", errors="surrogateescape")),
            "target": os.readlink(path),
        }
    if stat.S_ISREG(info.st_mode):
        return {"path": relative, "type": "file", "mode": mode, "sha256": sha256_file(path)}
    raise RecoveryError(f"unsupported recovery object: {relative}")


def _is_ignored(root: Path, relative: str) -> bool:
    result = _git(root, "check-ignore", "-q", "--no-index", "--", relative, check=False)
    return result.returncode == 0


def snapshot_worktree(root: Path, *, include_ignored: bool = False) -> tuple[dict[str, str], ...]:
    """Return exact non-.git/non-runtime worktree material including empty dirs."""
    root = root.resolve()
    rows: list[dict[str, str]] = []
    for directory, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        current = Path(directory)
        rel_dir = current.relative_to(root)
        kept_dirs: list[str] = []
        for name in sorted(dirnames):
            child = current / name
            relative = (rel_dir / name).as_posix()
            if relative == ".git" or relative.startswith(".git/") or relative == RUNTIME_NAME or relative.startswith(f"{RUNTIME_NAME}/"):
                continue
            if child.is_symlink():
                if include_ignored or not _is_ignored(root, relative):
                    rows.append(_record(child, relative))
                continue
            if not include_ignored and _is_ignored(root, relative + "/"):
                continue
            kept_dirs.append(name)
            rows.append(_record(child, relative))
        dirnames[:] = kept_dirs
        for name in sorted(filenames):
            child = current / name
            relative = (rel_dir / name).as_posix()
            if relative.startswith(".git/") or relative.startswith(f"{RUNTIME_NAME}/"):
                continue
            if not include_ignored and _is_ignored(root, relative):
                continue
            rows.append(_record(child, relative))
    return tuple(sorted(rows, key=lambda item: item["path"]))


def manifest_sha256(entries: Iterable[Mapping[str, str]]) -> str:
    return sha256_bytes(_canonical_json(list(entries)))


def _validate_relative(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise RecoveryError(f"unsafe recovery archive path: {name!r}")
    return path


def _archive_add(archive: tarfile.TarFile, root: Path, entry: Mapping[str, str]) -> None:
    relative = str(entry["path"])
    path = root / relative
    archive.add(path, arcname=relative, recursive=False)


def create_internal_checkpoint(root: Path, baseline: Mapping[str, Any]) -> dict[str, Any]:
    """Capture clean/new pre-authority material after HANDOFF authorization.

    This function must never be used for a dirty journey.  Dirty recovery stays
    operator-owned and external.
    """
    journey = str(baseline.get("journey") or "")
    if journey == "dirty":
        raise RecoveryError("dirty baselines must remain operator-owned and external")
    runtime = root.resolve() / RUNTIME_NAME
    recovery = runtime / INTERNAL_RECOVERY_DIR
    if recovery.exists():
        raise RecoveryError("pre-authority recovery checkpoint already exists")
    recovery.mkdir(parents=True, mode=0o700)
    os.chmod(runtime, 0o700)
    os.chmod(recovery, 0o700)

    entries = snapshot_worktree(root)
    archive_path = recovery / INTERNAL_ARCHIVE
    with tarfile.open(archive_path, "w") as archive:
        for entry in entries:
            _archive_add(archive, root, entry)
    os.chmod(archive_path, 0o600)

    index = root / ".git" / "index"
    index_path = recovery / INTERNAL_INDEX
    index_present = index.is_file()
    index_sha = None
    if index_present:
        shutil.copyfile(index, index_path)
        os.chmod(index_path, 0o600)
        index_sha = sha256_file(index_path)

    metadata = {
        "schema": INTERNAL_SCHEMA,
        "baseline": dict(baseline),
        "archive": INTERNAL_ARCHIVE,
        "archive_sha256": sha256_file(archive_path),
        "index": INTERNAL_INDEX if index_present else None,
        "index_sha256": index_sha,
        "worktree_manifest": list(entries),
        "worktree_manifest_sha256": manifest_sha256(entries),
    }
    metadata["checkpoint_sha256"] = sha256_bytes(_canonical_json(metadata))
    metadata_path = recovery / INTERNAL_METADATA
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(metadata_path, 0o600)
    return {
        "kind": "controller-internal",
        "metadata": f"{RUNTIME_NAME}/{INTERNAL_RECOVERY_DIR}/{INTERNAL_METADATA}",
        "checkpoint_sha256": metadata["checkpoint_sha256"],
        "baseline_sha256": baseline.get("sha256"),
    }


def load_internal_checkpoint(root: Path, expected_sha256: str | None = None) -> dict[str, Any]:
    recovery = root.resolve() / RUNTIME_NAME / INTERNAL_RECOVERY_DIR
    metadata_path = recovery / INTERNAL_METADATA
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecoveryError(f"cannot load internal recovery checkpoint: {exc}") from exc
    if metadata.get("schema") != INTERNAL_SCHEMA:
        raise RecoveryError("unsupported internal recovery checkpoint schema")
    recorded = str(metadata.get("checkpoint_sha256") or "")
    body = dict(metadata)
    body.pop("checkpoint_sha256", None)
    actual = sha256_bytes(_canonical_json(body))
    if actual != recorded or (expected_sha256 is not None and recorded != expected_sha256):
        raise RecoveryError("internal recovery checkpoint digest mismatch")
    archive = recovery / str(metadata.get("archive") or "")
    if not archive.is_file() or sha256_file(archive) != metadata.get("archive_sha256"):
        raise RecoveryError("internal recovery archive digest mismatch")
    index_name = metadata.get("index")
    if index_name:
        index = recovery / str(index_name)
        if not index.is_file() or sha256_file(index) != metadata.get("index_sha256"):
            raise RecoveryError("internal recovery index digest mismatch")
    if manifest_sha256(metadata.get("worktree_manifest") or []) != metadata.get("worktree_manifest_sha256"):
        raise RecoveryError("internal recovery manifest digest mismatch")
    return metadata


def _load_json_file(path: Path, *, description: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecoveryError(f"invalid {description}: {exc}") from exc
    if not isinstance(value, dict):
        raise RecoveryError(f"{description} must be a JSON object")
    return value


def _archive_members(capture: Path) -> list[tarfile.TarInfo]:
    try:
        with tarfile.open(capture, "r:*") as archive:
            return archive.getmembers()
    except (OSError, tarfile.TarError) as exc:
        raise RecoveryError(f"cannot read operator recovery capture: {exc}") from exc


def _extract_operator_material(capture: Path, destination: Path) -> tuple[Path, bytes | None]:
    """Extract only worktree material and .git/index from an operator archive."""
    members = _archive_members(capture)
    top_levels = {PurePosixPath(member.name).parts[0] for member in members if PurePosixPath(member.name).parts}
    if top_levels != {"repo"}:
        raise RecoveryError("operator recovery capture must have exactly one top-level 'repo' directory")

    repo = destination / "repo"
    repo.mkdir(parents=True)
    index_bytes: bytes | None = None
    symlink_paths: set[PurePosixPath] = set()
    with tarfile.open(capture, "r:*") as archive:
        for member in sorted(archive.getmembers(), key=lambda item: (len(PurePosixPath(item.name).parts), item.name)):
            full = _validate_relative(member.name)
            if full.parts[0] != "repo":
                raise RecoveryError("operator recovery capture contains material outside repo/")
            relative = PurePosixPath(*full.parts[1:])
            if not relative.parts:
                continue
            if any(parent in symlink_paths for parent in [PurePosixPath(*relative.parts[:i]) for i in range(1, len(relative.parts))]):
                raise RecoveryError(f"recovery archive nests content beneath symlink: {relative}")
            if relative.parts[0] == ".git":
                if relative == PurePosixPath(".git/index"):
                    stream = archive.extractfile(member)
                    if stream is None:
                        raise RecoveryError("operator recovery capture has unreadable .git/index")
                    index_bytes = stream.read()
                continue
            target = repo.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            if member.isdir():
                target.mkdir(exist_ok=True)
                os.chmod(target, member.mode & 0o7777)
            elif member.isreg():
                stream = archive.extractfile(member)
                if stream is None:
                    raise RecoveryError(f"cannot read recovery file: {relative}")
                with target.open("wb") as output:
                    shutil.copyfileobj(stream, output)
                os.chmod(target, member.mode & 0o7777)
            elif member.issym():
                os.symlink(member.linkname, target)
                symlink_paths.add(relative)
            else:
                raise RecoveryError(f"unsupported recovery archive member type: {relative}")
    return repo, index_bytes


def _git_against_snapshot(live_root: Path, snapshot_root: Path, index_path: Path | None, *args: str) -> bytes:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    if index_path is not None:
        environment["GIT_INDEX_FILE"] = str(index_path)
    result = subprocess.run(
        ["git", f"--git-dir={live_root / '.git'}", f"--work-tree={snapshot_root}", *args],
        env=environment,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RecoveryError(
            f"git snapshot {' '.join(args)} failed ({result.returncode}): "
            f"{(result.stderr or result.stdout).decode('utf-8', errors='replace').strip()}"
        )
    return result.stdout


def _status_categories(status: str) -> list[str]:
    categories: set[str] = set()
    for line in status.splitlines():
        if len(line) < 2:
            continue
        code = line[:2]
        if code == "??":
            categories.add("untracked")
            continue
        if code[0] not in {" ", "?"}:
            categories.add("staged")
        if code[1] != " ":
            categories.add("unstaged")
        if "R" in code:
            categories.add("renamed")
        if "D" in code:
            categories.add("deleted")
    return sorted(categories)


def verify_operator_dirty_package(root: Path, attestation_path: Path, baseline: Mapping[str, Any]) -> dict[str, Any]:
    attestation_path = attestation_path.expanduser().resolve()
    attestation = _load_json_file(attestation_path, description="dirty recovery attestation")
    if attestation.get("schema") != "stygnox_dirty_recovery_attestation_v1":
        raise RecoveryError("unsupported dirty recovery attestation schema")
    if Path(str(attestation.get("worktree") or "")).expanduser().resolve() != root.resolve():
        raise RecoveryError("dirty recovery attestation worktree does not match adopted project")
    if attestation.get("verified") is not True or attestation.get("restoration_rehearsed") is not True:
        raise RecoveryError("dirty recovery attestation is not externally verified/rehearsed")
    if not str(attestation.get("verified_by") or "").strip():
        raise RecoveryError("dirty recovery attestation requires verified_by")
    capture = Path(str(attestation.get("capture_path") or "")).expanduser().resolve()
    manifest_path = Path(str(attestation.get("manifest_path") or "")).expanduser().resolve()
    if not capture.is_file() or capture.is_symlink():
        raise RecoveryError("dirty recovery capture is missing or not a regular external file")
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise RecoveryError("dirty recovery manifest is missing or not a regular external file")
    if sha256_file(capture) != attestation.get("capture_sha256"):
        raise RecoveryError("dirty recovery capture digest verification failed")
    if sha256_file(manifest_path) != attestation.get("manifest_sha256"):
        raise RecoveryError("dirty recovery manifest digest verification failed")
    if attestation.get("baseline_sha256") != baseline.get("sha256"):
        raise RecoveryError("dirty recovery attestation baseline no longer matches handoff")

    manifest = _load_json_file(manifest_path, description="operator recovery manifest")
    if manifest.get("schema") != OPERATOR_MANIFEST_SCHEMA:
        raise RecoveryError("unsupported operator recovery manifest schema")
    if manifest.get("baseline_sha256") != baseline.get("sha256"):
        raise RecoveryError("operator recovery manifest baseline does not match handoff")

    with tempfile.TemporaryDirectory(prefix="stygnox-d83-verify-") as temp:
        temporary = Path(temp)
        snapshot_root, index_bytes = _extract_operator_material(capture, temporary)
        index_path: Path | None = None
        if index_bytes is not None:
            index_path = temporary / "index"
            index_path.write_bytes(index_bytes)
        expected_index_sha = manifest.get("index_file_sha256")
        actual_index_sha = sha256_bytes(index_bytes) if index_bytes is not None else None
        if actual_index_sha != expected_index_sha:
            raise RecoveryError("operator recovery raw index digest mismatch")

        entries = snapshot_worktree(snapshot_root, include_ignored=True)
        if list(entries) != manifest.get("worktree_manifest"):
            raise RecoveryError("operator recovery worktree manifest does not match capture")
        if manifest_sha256(entries) != manifest.get("worktree_manifest_sha256"):
            raise RecoveryError("operator recovery worktree manifest digest mismatch")

        status = _git_against_snapshot(root, snapshot_root, index_path, "status", "--porcelain=v1", "--untracked-files=all").decode("utf-8", errors="surrogateescape")
        staged = _git_against_snapshot(root, snapshot_root, index_path, "diff", "--cached", "--binary", "--no-ext-diff", "--no-textconv")
        unstaged = _git_against_snapshot(root, snapshot_root, index_path, "diff", "--binary", "--no-ext-diff", "--no-textconv")
        if status != baseline.get("status"):
            raise RecoveryError("operator recovery capture does not reproduce baseline Git status")
        if sha256_bytes(staged) != baseline.get("staged_sha256"):
            raise RecoveryError("operator recovery capture does not reproduce staged baseline")
        if sha256_bytes(unstaged) != baseline.get("unstaged_sha256"):
            raise RecoveryError("operator recovery capture does not reproduce unstaged baseline")
        if _status_categories(status) != sorted(str(item) for item in baseline.get("dirty_categories") or []):
            raise RecoveryError("operator recovery capture dirty categories do not match baseline")

    return {
        "kind": "operator-external",
        "attestation_path": str(attestation_path),
        "attestation_sha256": sha256_file(attestation_path),
        "capture_path": str(capture),
        "capture_sha256": sha256_file(capture),
        "manifest_path": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "baseline_sha256": baseline.get("sha256"),
    }


def ensure_runtime_local_ignore(root: Path) -> None:
    exclude = root.resolve() / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    before = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    lines = {line.strip() for line in before.splitlines()}
    if LOCAL_EXCLUDE_PATTERN in lines or ".stygnox/" in lines:
        return
    suffix = "" if not before or before.endswith("\n") else "\n"
    exclude.write_text(before + suffix + f"\n{LOCAL_EXCLUDE_MARKER}\n{LOCAL_EXCLUDE_PATTERN}\n", encoding="utf-8")


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _restore_manifest(root: Path, source_root: Path, entries: list[dict[str, str]]) -> None:
    desired = {str(entry["path"]): entry for entry in entries}
    current = {str(entry["path"]): entry for entry in snapshot_worktree(root)}

    for relative in sorted(set(current) - set(desired), key=lambda value: (value.count("/"), value), reverse=True):
        _remove_path(root / relative)

    # Type conflicts must be removed before parents/children are recreated.
    for relative, entry in desired.items():
        path = root / relative
        if not path.exists() and not path.is_symlink():
            continue
        mode = path.lstat().st_mode
        actual_type = "symlink" if stat.S_ISLNK(mode) else "dir" if stat.S_ISDIR(mode) else "file" if stat.S_ISREG(mode) else "other"
        if actual_type != entry["type"]:
            _remove_path(path)

    for entry in sorted(entries, key=lambda item: (str(item["path"]).count("/"), str(item["path"]))):
        relative = str(entry["path"])
        source = source_root / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if entry["type"] == "dir":
            target.mkdir(exist_ok=True)
            os.chmod(target, int(entry["mode"], 8))
        elif entry["type"] == "symlink":
            if target.exists() or target.is_symlink():
                _remove_path(target)
            os.symlink(os.readlink(source), target)
        elif entry["type"] == "file":
            shutil.copyfile(source, target, follow_symlinks=False)
            os.chmod(target, int(entry["mode"], 8))
        else:
            raise RecoveryError(f"unsupported restore object type: {entry['type']}")


def _set_head(root: Path, baseline: Mapping[str, Any]) -> None:
    head = baseline.get("head")
    branch = str(baseline.get("branch") or "")
    if head:
        if branch and branch != "(detached)":
            ref = f"refs/heads/{branch}"
            _git(root, "symbolic-ref", "HEAD", ref)
            _git(root, "update-ref", ref, str(head))
        else:
            _git(root, "update-ref", "--no-deref", "HEAD", str(head))
    else:
        if not branch or branch == "(detached)":
            raise RecoveryError("unborn recovery baseline lacks a branch name")
        ref = f"refs/heads/{branch}"
        _git(root, "symbolic-ref", "HEAD", ref)
        _git(root, "update-ref", "-d", ref, check=False)


def _replace_index(root: Path, index_bytes: bytes | None) -> None:
    index = root / ".git" / "index"
    if index_bytes is None:
        if index.exists():
            index.unlink()
        return
    temporary = index.with_name(f"index.stygnox-recovery-{os.getpid()}")
    temporary.write_bytes(index_bytes)
    os.replace(temporary, index)


def restore_internal(root: Path, metadata: Mapping[str, Any]) -> None:
    recovery = root.resolve() / RUNTIME_NAME / INTERNAL_RECOVERY_DIR
    archive_path = recovery / str(metadata["archive"])
    with tempfile.TemporaryDirectory(prefix="stygnox-d83-internal-restore-") as temp:
        source = Path(temp) / "snapshot"
        source.mkdir()
        # Internal archives contain only validated paths created by Stygnox.
        with tarfile.open(archive_path, "r") as archive:
            for member in archive.getmembers():
                relative = _validate_relative(member.name)
                target = source.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                if member.isdir():
                    target.mkdir(exist_ok=True)
                    os.chmod(target, member.mode & 0o7777)
                elif member.isreg():
                    stream = archive.extractfile(member)
                    if stream is None:
                        raise RecoveryError(f"cannot read internal recovery member: {relative}")
                    with target.open("wb") as output:
                        shutil.copyfileobj(stream, output)
                    os.chmod(target, member.mode & 0o7777)
                elif member.issym():
                    os.symlink(member.linkname, target)
                else:
                    raise RecoveryError(f"unsupported internal recovery member: {relative}")
        _set_head(root, metadata["baseline"])
        index_bytes = None
        if metadata.get("index"):
            index_bytes = (recovery / str(metadata["index"])).read_bytes()
        _replace_index(root, index_bytes)
        _restore_manifest(root, source, list(metadata["worktree_manifest"]))


def restore_external(root: Path, source: Mapping[str, Any], baseline: Mapping[str, Any]) -> None:
    capture = Path(str(source["capture_path"]))
    manifest = _load_json_file(Path(str(source["manifest_path"])), description="operator recovery manifest")
    with tempfile.TemporaryDirectory(prefix="stygnox-d83-external-restore-") as temp:
        temporary = Path(temp)
        snapshot_root, index_bytes = _extract_operator_material(capture, temporary)
        _set_head(root, baseline)
        _replace_index(root, index_bytes)
        _restore_manifest(root, snapshot_root, list(manifest["worktree_manifest"]))
