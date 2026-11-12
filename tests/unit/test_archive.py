"""Unit and security tests for WorkspaceArchiveSerializer, SecureTarImporter,
atomic staging-directory commits, crash recovery, durability fsync ordering,
short writes, and Docker execution sync/cleanup handling.
"""

from __future__ import annotations

import errno
import gzip
import io
import os
import tarfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests.exceptions
from docker.errors import APIError, DockerException

from app.core.config import SandboxSettings
from app.core.exceptions import (
    DockerEngineError,
    FileQuotaExceededError,
    PathTraversalError,
    WorkspaceCleanupError,
    WorkspaceRollbackError,
)
from app.sandbox.archive import (
    APPROVED_ARCHIVE_GID,
    APPROVED_ARCHIVE_UID,
    SecureTarImporter,
    WorkspaceArchiveSerializer,
)
from app.sandbox.engine import EphemeralSandboxEngine
from app.sandbox.schemas import ExecutionRequest, ExecutionStatus
from app.sandbox.workspace import WorkspaceManager


@pytest.fixture(autouse=True)
def verify_no_container_leak():
    """Archive unit tests do not interact with a live Docker daemon."""
    yield


@pytest.fixture
def archive_settings(tmp_path: Path) -> SandboxSettings:
    """Restrictive workspace & archive settings for fast unit testing."""
    return SandboxSettings(
        WORKSPACE_DIR=tmp_path / "workspaces",
        MAX_FILE_SIZE_BYTES=2048,
        MAX_WORKSPACE_SIZE_BYTES=8192,
        MAX_DECOMPRESSED_BYTES=8192,
        MAX_ARCHIVE_BYTES=32768,
        MAX_FILE_COUNT=10,
        MAX_ARCHIVE_ENTRIES=15,
        MAX_DIRECTORY_DEPTH=4,
        MAX_PATH_LENGTH=140,
        MAX_READ_RESPONSE_BYTES=4096,
        MAX_FILE_LIST_ENTRIES=50,
        PROJECT_LABEL="ai-sandbox-test",
        MANAGED_BY_LABEL="ai-sandbox-platform-test",
    )


@pytest.fixture
def manager(archive_settings: SandboxSettings) -> WorkspaceManager:
    return WorkspaceManager(config=archive_settings)


@pytest.fixture
def serializer(manager: WorkspaceManager) -> WorkspaceArchiveSerializer:
    return WorkspaceArchiveSerializer(manager)


@pytest.fixture
def importer(manager: WorkspaceManager) -> SecureTarImporter:
    return SecureTarImporter(manager)


def _build_tar_bytes(
    entries: list[tuple[tarfile.TarInfo, bytes | None]],
    *,
    tar_format: int = tarfile.PAX_FORMAT,
    pax_headers: dict[str, str] | None = None,
) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(
        fileobj=buf,
        mode="w",
        format=tar_format,
        pax_headers=pax_headers,
    ) as tf:
        for info, payload in entries:
            if "\x00" in info.name:
                raw_target = info.name
                info.name = "pax_placeholder"
                info.pax_headers = {"path": raw_target}
            if payload is not None:
                info.size = len(payload)
                tf.addfile(info, io.BytesIO(payload))
            else:
                tf.addfile(info)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# WorkspaceArchiveSerializer Tests
# ---------------------------------------------------------------------------


def test_serialize_normal_files_nested_and_empty_dirs(
    manager: WorkspaceManager,
    serializer: WorkspaceArchiveSerializer,
    importer: SecureTarImporter,
):
    src_id = "src-ws"
    dst_id = "dst-ws"

    manager.write_file(src_id, "root.txt", "root content")
    manager.write_file(src_id, "pkg/module.py", "x = 42\n")
    manager.create_directory(src_id, "empty_dir/sub_empty")

    with serializer.serialize(src_id, include_root_entry=True) as spool:
        with tarfile.open(fileobj=spool, mode="r:*") as tf:
            members = tf.getmembers()
            names = [m.name for m in members]
            assert "" in names or "/" in names
            assert "root.txt" in names
            assert "pkg" in names
            assert "pkg/module.py" in names
            assert "empty_dir" in names
            assert "empty_dir/sub_empty" in names

            for m in members:
                assert m.uid == APPROVED_ARCHIVE_UID
                assert m.gid == APPROVED_ARCHIVE_GID
                if m.isdir():
                    assert m.mode == 0o700
                elif m.isreg():
                    assert m.mode == 0o600

        spool.seek(0)
        importer.import_archive(dst_id, spool, strip_root_prefix="workspace")

    assert manager.read_file(dst_id, "root.txt").content == "root content"
    assert manager.read_file(dst_id, "pkg/module.py").content == "x = 42\n"
    listed = {f.path: f for f in manager.list_files(dst_id).files}
    assert "empty_dir" in listed and listed["empty_dir"].is_directory is True
    assert "empty_dir/sub_empty" in listed and listed["empty_dir/sub_empty"].is_directory is True


def test_serializer_and_importer_preserve_user_dot_tmp_staging_backup_files(
    manager: WorkspaceManager,
    serializer: WorkspaceArchiveSerializer,
    importer: SecureTarImporter,
):
    src_id = "src-dot-prefixes"
    dst_id = "dst-dot-prefixes"

    manager.write_file(src_id, ".tmp.user.txt", "user tmp content")
    manager.write_file(src_id, ".staging.config.yaml", "env: staging")
    manager.write_file(src_id, ".backup.db.sql", "CREATE TABLE t (id INT);")
    manager.write_file(src_id, "sub/.tmp.nested.json", '{"ok": true}')

    with serializer.serialize(src_id, include_root_entry=True) as spool:
        importer.import_archive(dst_id, spool, strip_root_prefix="workspace")

    assert manager.read_file(dst_id, ".tmp.user.txt").content == "user tmp content"
    assert manager.read_file(dst_id, ".staging.config.yaml").content == "env: staging"
    assert manager.read_file(dst_id, ".backup.db.sql").content == "CREATE TABLE t (id INT);"
    assert manager.read_file(dst_id, "sub/.tmp.nested.json").content == '{"ok": true}'


def test_serialize_large_file_within_limits_and_spool_rollover(tmp_path: Path):
    # Configure limits large enough for a 1.2 MB file so SpooledTemporaryFile
    # rolls over its 1 MB in-memory threshold onto disk.
    large_settings = SandboxSettings(
        WORKSPACE_DIR=tmp_path / "large_ws",
        MAX_FILE_SIZE_BYTES=2 * 1024 * 1024,
        MAX_WORKSPACE_SIZE_BYTES=4 * 1024 * 1024,
        MAX_DECOMPRESSED_BYTES=4 * 1024 * 1024,
        MAX_ARCHIVE_BYTES=5 * 1024 * 1024,
    )
    mgr = WorkspaceManager(config=large_settings)
    ser = WorkspaceArchiveSerializer(mgr)
    imp = SecureTarImporter(mgr)

    payload = "A" * (1200 * 1024)  # 1.2 MB (> 1 MB spool rollover threshold, > 64 KB chunk size)
    mgr.write_file("large-src", "big.txt", payload)

    with ser.serialize("large-src") as spool:
        assert spool._rolled is True
        imp.import_archive("large-dst", spool, strip_root_prefix="workspace")

    assert mgr.read_file("large-dst", "big.txt").content == payload


def test_serialize_rejects_symlinks(
    manager: WorkspaceManager,
    serializer: WorkspaceArchiveSerializer,
):
    sandbox_id = "ser-symlink"
    manager.write_file(sandbox_id, "ok.txt", "safe")
    ws_path = manager.get_workspace_path(sandbox_id)
    os.symlink("/etc/hosts", ws_path / "evil_link.txt")

    with pytest.raises(PathTraversalError) as excinfo:
        serializer.serialize(sandbox_id)
    assert "symlink" in str(excinfo.value).lower()


def test_serialize_rejects_hard_links(
    manager: WorkspaceManager,
    serializer: WorkspaceArchiveSerializer,
):
    sandbox_id = "ser-hardlink"
    manager.write_file(sandbox_id, "original.txt", "data")
    ws_path = manager.get_workspace_path(sandbox_id)
    os.link(ws_path / "original.txt", ws_path / "hardlinked.txt")

    with pytest.raises(PathTraversalError) as excinfo:
        serializer.serialize(sandbox_id)
    assert "hard link" in str(excinfo.value).lower()


def test_serialize_rejects_special_files(
    manager: WorkspaceManager,
    serializer: WorkspaceArchiveSerializer,
):
    sandbox_id = "ser-fifo"
    manager.write_file(sandbox_id, "ok.txt", "safe")
    ws_path = manager.get_workspace_path(sandbox_id)
    fifo_path = ws_path / "named_pipe"
    try:
        os.mkfifo(str(fifo_path))
    except (AttributeError, OSError):
        pytest.skip("mkfifo not supported on this filesystem")

    with pytest.raises(PathTraversalError) as excinfo:
        serializer.serialize(sandbox_id)
    assert "special file" in str(excinfo.value).lower()


def test_serialize_enforces_size_and_entry_limits(
    manager: WorkspaceManager,
    serializer: WorkspaceArchiveSerializer,
):
    sandbox_id = "ser-quota"
    ws_path = manager.get_workspace_path(sandbox_id)
    ws_path.mkdir(parents=True, exist_ok=True)
    os.chmod(ws_path, 0o700)

    # Create a file directly on disk exceeding MAX_FILE_SIZE_BYTES (2048)
    (ws_path / "too_big.txt").write_bytes(b"X" * 3000)

    with pytest.raises(FileQuotaExceededError):
        serializer.serialize(sandbox_id)


# ---------------------------------------------------------------------------
# SecureTarImporter Security, Metadata & Validation Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_archive_name",
    [
        "/etc/passwd",
        "/absolute/file.txt",
        "../escape.txt",
        "sub/../../escape.txt",
        "workspace/../escape.txt",
        "C:windows/system.ini",
        "win\\path\\file.txt",
        "null\x00byte.txt",
        "ctrl\x07bell.txt",
        "newline\ninjected.txt",
        "./relative_dot.txt",
        "a//double_slash.txt",
    ],
)
def test_importer_rejects_malicious_paths(
    importer: SecureTarImporter,
    bad_archive_name: str,
):
    ti = tarfile.TarInfo(bad_archive_name)
    ti.type = tarfile.REGTYPE
    raw_tar = _build_tar_bytes([(ti, b"malicious")])

    with pytest.raises(PathTraversalError):
        importer.import_archive("imp-bad-path", raw_tar)


@pytest.mark.parametrize(
    ("entry_type", "linkname"),
    [
        (tarfile.SYMTYPE, "/etc/passwd"),
        (tarfile.LNKTYPE, "other.txt"),
        (tarfile.FIFOTYPE, ""),
        (tarfile.CHRTYPE, ""),
        (tarfile.BLKTYPE, ""),
        (b"X", ""),
    ],
)
def test_importer_rejects_links_devices_and_unknown_types(
    importer: SecureTarImporter,
    entry_type: bytes,
    linkname: str,
):
    ti = tarfile.TarInfo("special_entry")
    ti.type = entry_type
    ti.linkname = linkname
    payload = b"data" if entry_type == b"X" else None
    raw_tar = _build_tar_bytes([(ti, payload)])

    with pytest.raises(PathTraversalError):
        importer.import_archive("imp-special-type", raw_tar)


def test_importer_rejects_pax_linkpath_header(importer: SecureTarImporter):
    # Case 1: Regular file entry smuggling a PAX linkpath header
    ti_reg = tarfile.TarInfo("innocent.txt")
    ti_reg.type = tarfile.REGTYPE
    ti_reg.pax_headers = {"linkpath": "/etc/passwd"}
    raw_tar_reg = _build_tar_bytes([(ti_reg, b"payload")])

    with pytest.raises(PathTraversalError) as excinfo:
        importer.import_archive("imp-pax-linkpath-reg", raw_tar_reg)
    assert "link" in str(excinfo.value).lower()

    # Case 2: Symlink with long PAX linkpath
    ti_sym = tarfile.TarInfo("link_entry")
    ti_sym.type = tarfile.SYMTYPE
    ti_sym.linkname = "/" + ("a/" * 60) + "etc/shadow"
    raw_tar_sym = _build_tar_bytes([(ti_sym, None)])

    with pytest.raises(PathTraversalError):
        importer.import_archive("imp-pax-linkpath-sym", raw_tar_sym)


@pytest.mark.parametrize(
    "pax_override_path",
    [
        "../../etc/passwd",
        "/etc/shadow",
        "workspace/../../escape.txt",
        "sub/\x00hidden.txt",
    ],
)
def test_importer_rejects_pax_path_override_traversal(
    importer: SecureTarImporter,
    pax_override_path: str,
):
    # USTAR 100-byte name field is benign ("safe_name.txt"), but PAX extended header
    # overrides effective path to a traversal/absolute/null-byte target.
    ti = tarfile.TarInfo("safe_name.txt")
    ti.type = tarfile.REGTYPE
    ti.pax_headers = {"path": pax_override_path}
    raw_tar = _build_tar_bytes([(ti, b"escaped")])

    with pytest.raises(PathTraversalError):
        importer.import_archive("imp-pax-path-override", raw_tar, strip_root_prefix="workspace")


def test_importer_gnu_longname_valid_and_traversal_rejected(
    manager: WorkspaceManager,
    importer: SecureTarImporter,
):
    # 1. Valid GNU LONGNAME (> 100 chars so GNU ././@LongLink type 'L' is emitted,
    #    within MAX_PATH_LENGTH = 140)
    long_dir = "a" * 55
    long_file = "b" * 55 + ".txt"
    valid_long_path = f"{long_dir}/{long_file}"  # 115 chars (> 100, <= 140)
    assert 100 < len(valid_long_path) <= manager.config.MAX_PATH_LENGTH

    ti_valid = tarfile.TarInfo(valid_long_path)
    ti_valid.type = tarfile.REGTYPE
    gnu_valid_tar = _build_tar_bytes(
        [(ti_valid, b"gnu longname content")],
        tar_format=tarfile.GNU_FORMAT,
    )
    assert b"././@LongLink" in gnu_valid_tar

    importer.import_archive("imp-gnu-longname-ok", gnu_valid_tar)
    assert (
        manager.read_file("imp-gnu-longname-ok", valid_long_path).content == "gnu longname content"
    )

    # 2. Malicious GNU LONGNAME containing '..' traversal after >100-char prefix
    traversal_long_path = ("a" * 60) + "/" + ("b" * 50) + "/../../../escape.txt"
    ti_trav = tarfile.TarInfo(traversal_long_path)
    ti_trav.type = tarfile.REGTYPE
    gnu_trav_tar = _build_tar_bytes(
        [(ti_trav, b"evil")],
        tar_format=tarfile.GNU_FORMAT,
    )
    with pytest.raises(PathTraversalError):
        importer.import_archive("imp-gnu-longname-trav", gnu_trav_tar)

    # 3. GNU LONGNAME exceeding MAX_PATH_LENGTH (140)
    too_long_path = ("a" * 80) + "/" + ("b" * 80) + ".txt"
    ti_exceed = tarfile.TarInfo(too_long_path)
    ti_exceed.type = tarfile.REGTYPE
    gnu_exceed_tar = _build_tar_bytes(
        [(ti_exceed, b"too long")],
        tar_format=tarfile.GNU_FORMAT,
    )
    with pytest.raises(PathTraversalError) as excinfo:
        importer.import_archive("imp-gnu-longname-max", gnu_exceed_tar)
    assert "length" in str(excinfo.value).lower()


def test_importer_rejects_gnu_longlink(importer: SecureTarImporter):
    # > 100-char linkname triggers GNU ././@LongLink type 'K' (GNUTYPE_LONGLINK)
    long_target = "/" + (" usr_local_lib/" * 10) + "secret.so"
    assert len(long_target) > 100

    # Both SYMTYPE and LNKTYPE with GNU LONGLINK must be rejected
    for link_type in (tarfile.SYMTYPE, tarfile.LNKTYPE):
        ti = tarfile.TarInfo("gnu_longlink_entry")
        ti.type = link_type
        ti.linkname = long_target
        gnu_tar = _build_tar_bytes([(ti, None)], tar_format=tarfile.GNU_FORMAT)
        assert b"././@LongLink" in gnu_tar

        with pytest.raises(PathTraversalError):
            importer.import_archive("imp-gnu-longlink", gnu_tar)


def test_importer_rejects_duplicate_paths(importer: SecureTarImporter):
    t1 = tarfile.TarInfo("dup.txt")
    t2 = tarfile.TarInfo("dup.txt")
    raw_tar = _build_tar_bytes([(t1, b"first"), (t2, b"second")])

    with pytest.raises(PathTraversalError) as excinfo:
        importer.import_archive("imp-dup", raw_tar)
    assert "duplicate" in str(excinfo.value).lower()


def test_importer_rejects_duplicate_paths_after_root_prefix_normalization(
    importer: SecureTarImporter,
):
    # "workspace/pkg/app.py" and "pkg/app.py" both normalize to "pkg/app.py"
    # when strip_root_prefix="workspace" is active.
    t1 = tarfile.TarInfo("workspace/pkg/app.py")
    t2 = tarfile.TarInfo("pkg/app.py")
    raw_tar = _build_tar_bytes([(t1, b"v1"), (t2, b"v2")])

    with pytest.raises(PathTraversalError) as excinfo:
        importer.import_archive("imp-norm-dup", raw_tar, strip_root_prefix="workspace")
    assert "duplicate" in str(excinfo.value).lower()


def test_importer_rejects_file_directory_conflicts_including_after_normalization(
    importer: SecureTarImporter,
):
    # Case 1: 'workspace/conflict' is a regular file, followed by 'conflict/child.txt'
    # under strip_root_prefix="workspace"
    f_info = tarfile.TarInfo("workspace/conflict")
    f_info.type = tarfile.REGTYPE
    c_info = tarfile.TarInfo("conflict/child.txt")
    c_info.type = tarfile.REGTYPE
    raw_tar_1 = _build_tar_bytes([(f_info, b"file"), (c_info, b"child")])

    with pytest.raises(PathTraversalError) as excinfo:
        importer.import_archive("imp-conflict-1", raw_tar_1, strip_root_prefix="workspace")
    assert "conflict" in str(excinfo.value).lower()

    # Case 2: 'workspace/dir_first/child.txt' creates implicit dir 'dir_first',
    # followed by regular file 'dir_first'
    c2_info = tarfile.TarInfo("workspace/dir_first/child.txt")
    c2_info.type = tarfile.REGTYPE
    f2_info = tarfile.TarInfo("dir_first")
    f2_info.type = tarfile.REGTYPE
    raw_tar_2 = _build_tar_bytes([(c2_info, b"child"), (f2_info, b"file")])

    with pytest.raises(PathTraversalError) as excinfo:
        importer.import_archive("imp-conflict-2", raw_tar_2, strip_root_prefix="workspace")
    assert "conflict" in str(excinfo.value).lower()


def test_importer_rejects_malformed_archive_headers_and_extended_metadata(
    importer: SecureTarImporter,
):
    # 1. Completely invalid header bytes
    with pytest.raises(PathTraversalError):
        importer.import_archive("imp-corrupt", b"not a valid tar header at all" * 20)

    # 2. Global PAX header attempting to set 'path' globally
    ti = tarfile.TarInfo("normal.txt")
    raw_global_pax = _build_tar_bytes(
        [(ti, b"data")],
        pax_headers={"path": "forced_name.txt"},
    )
    with pytest.raises(PathTraversalError):
        importer.import_archive("imp-global-pax", raw_global_pax)

    # 3. Corrupted PAX extended header block (XHDTYPE = b'x' with malformed non-numeric record)
    corrupt_xhd = tarfile.TarInfo("././@PaxHeader")
    corrupt_xhd.type = tarfile.XHDTYPE
    bad_pax_payload = b"NOT_A_LENGTH path=evil.txt\n"
    corrupt_xhd.size = len(bad_pax_payload)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        tf.addfile(corrupt_xhd, io.BytesIO(bad_pax_payload))
        next_ti = tarfile.TarInfo("after_pax.txt")
        next_ti.size = 4
        tf.addfile(next_ti, io.BytesIO(b"test"))
    with pytest.raises(PathTraversalError):
        importer.import_archive("imp-corrupt-pax", buf.getvalue())


def test_importer_rejects_truncated_archive_payload(
    manager: WorkspaceManager,
    importer: SecureTarImporter,
):
    sandbox_id = "imp-truncated"
    manager.write_file(sandbox_id, "existing.txt", "untouched")

    ti = tarfile.TarInfo("truncated.bin")
    ti.type = tarfile.REGTYPE
    full_tar = _build_tar_bytes([(ti, b"A" * 1024)])
    # Slice the archive mid-payload (after header + ~200 bytes of the 1024-byte file)
    truncated_tar = full_tar[:1200]

    with pytest.raises(PathTraversalError):
        importer.import_archive(sandbox_id, truncated_tar)

    assert manager.read_file(sandbox_id, "existing.txt").content == "untouched"
    assert list(manager.base_dir.glob(f".staging.{sandbox_id}.*")) == []


def test_importer_rejects_decompression_bomb_and_size_limits(importer: SecureTarImporter):
    # Build a highly compressible gzip tar bomb:
    # 5 files x 2048 bytes = 10,240 decompressed bytes (> MAX_DECOMPRESSED_BYTES = 8192),
    # while gzipped stream is < 500 bytes (well under MAX_ARCHIVE_BYTES = 32768).
    raw_buf = io.BytesIO()
    with tarfile.open(fileobj=raw_buf, mode="w") as tf:
        for i in range(5):
            ti = tarfile.TarInfo(f"zero_{i}.bin")
            ti.size = 2048
            tf.addfile(ti, io.BytesIO(b"\x00" * 2048))
    compressed_bomb = gzip.compress(raw_buf.getvalue())
    assert len(compressed_bomb) < 1024

    with pytest.raises(FileQuotaExceededError) as excinfo:
        importer.import_archive("imp-bomb", compressed_bomb)
    assert "decompressed" in str(excinfo.value).lower()


def test_importer_rejects_oversized_archive_stream(importer: SecureTarImporter):
    # Stream exceeds MAX_ARCHIVE_BYTES (32768)
    huge_stream = [b"\x00" * 16384 for _ in range(3)]
    with pytest.raises(FileQuotaExceededError) as excinfo:
        importer.import_archive("imp-stream-limit", huge_stream)
    assert "stream exceeds" in str(excinfo.value).lower()


def test_importer_rejects_entry_count_and_depth_limits(importer: SecureTarImporter):
    # MAX_DIRECTORY_DEPTH is 4
    deep_info = tarfile.TarInfo("a/b/c/d/e/deep.txt")
    raw_deep = _build_tar_bytes([(deep_info, b"deep")])
    with pytest.raises(PathTraversalError) as excinfo:
        importer.import_archive("imp-depth", raw_deep)
    assert "depth" in str(excinfo.value).lower()

    # MAX_FILE_COUNT is 10
    many_entries = [(tarfile.TarInfo(f"f_{i}.txt"), b"x") for i in range(11)]
    raw_many = _build_tar_bytes(many_entries)
    with pytest.raises(FileQuotaExceededError) as excinfo:
        importer.import_archive("imp-count", raw_many)
    assert "count" in str(excinfo.value).lower()


def test_importer_handles_partial_and_interrupted_os_writes(
    manager: WorkspaceManager,
    importer: SecureTarImporter,
    monkeypatch: pytest.MonkeyPatch,
):
    sandbox_id = "imp-short-write"
    payload = b"Archive extraction payload with partial writes and EINTR!"
    ti = tarfile.TarInfo("extracted.txt")
    raw_tar = _build_tar_bytes([(ti, payload)])

    real_write = os.write
    calls = 0

    def partial_write(fd: int, data: bytes | memoryview) -> int:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise InterruptedError("Simulated signal during tar extraction")
        if calls == 4:
            raise OSError(errno.EINTR, "Simulated EINTR during tar extraction")
        view = memoryview(data)
        return real_write(fd, view[:5])

    monkeypatch.setattr(os, "write", partial_write)
    importer.import_archive(sandbox_id, raw_tar)
    monkeypatch.undo()

    assert calls > 10
    assert manager.read_file(sandbox_id, "extracted.txt").content == payload.decode("utf-8")


# ---------------------------------------------------------------------------
# Rollback, Commit Failure Preservation, Crash Points & Durability Tests
# ---------------------------------------------------------------------------


def test_rollback_after_failed_validation_preserves_previous_workspace(
    manager: WorkspaceManager,
    importer: SecureTarImporter,
):
    sandbox_id = "rollback-validation"
    manager.write_file(sandbox_id, "existing.txt", "original safe data")
    manager.write_file(sandbox_id, "sub/keep.txt", "keep me")

    # Archive has a valid entry first, followed by a malicious symlink entry
    valid_ti = tarfile.TarInfo("existing.txt")
    evil_ti = tarfile.TarInfo("evil_symlink")
    evil_ti.type = tarfile.SYMTYPE
    evil_ti.linkname = "/etc/shadow"
    bad_tar = _build_tar_bytes([(valid_ti, b"overwritten!"), (evil_ti, None)])

    with pytest.raises(PathTraversalError):
        importer.import_archive(sandbox_id, bad_tar)

    # Previous workspace must remain completely untouched
    assert manager.read_file(sandbox_id, "existing.txt").content == "original safe data"
    assert (
        manager.read_file(
            sandbox_id,
            "sub/keep.txt",
        ).content
        == "keep me"
    )
    # No leftover staging directories
    staging_leftovers = list(manager.base_dir.glob(f".staging.{sandbox_id}.*"))
    assert staging_leftovers == []


def test_previous_workspace_preserved_when_atomic_commit_rename_fails(
    manager: WorkspaceManager,
    importer: SecureTarImporter,
    monkeypatch: pytest.MonkeyPatch,
):
    sandbox_id = "rollback-commit-fail"
    manager.write_file(sandbox_id, "precious.txt", "must survive commit error")

    new_ti = tarfile.TarInfo("precious.txt")
    valid_tar = _build_tar_bytes([(new_ti, b"new version")])

    real_rename = os.rename
    rename_calls = 0

    def failing_on_second_rename(src, dst, *args, **kwargs):
        nonlocal rename_calls
        if not kwargs.get("src_dir_fd") and ".staging." in str(src):
            rename_calls += 1
            raise OSError("Simulated filesystem failure during staging commit")
        return real_rename(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "rename", failing_on_second_rename)

    with pytest.raises(WorkspaceCleanupError):
        importer.import_archive(sandbox_id, valid_tar)

    assert rename_calls == 1
    monkeypatch.undo()
    assert manager.read_file(sandbox_id, "precious.txt").content == "must survive commit error"
    assert list(manager.base_dir.glob(f".staging.{sandbox_id}.*")) == []
    assert list(manager.base_dir.glob(f".backup.{sandbox_id}.*")) == []


def test_staging_rename_failure_followed_by_rollback_rename_failure(
    manager: WorkspaceManager,
    importer: SecureTarImporter,
    monkeypatch: pytest.MonkeyPatch,
):
    sandbox_id = "double-rename-fail"
    manager.write_file(sandbox_id, "vital.txt", "only valid generation")

    new_ti = tarfile.TarInfo("vital.txt")
    valid_tar = _build_tar_bytes([(new_ti, b"uncommitted update")])

    real_rename = os.rename

    def failing_commit_and_rollback(src, dst, *args, **kwargs):
        # Allow moving ws_path -> backup_path, but fail staging -> ws_path AND backup -> ws_path
        if not kwargs.get("src_dir_fd"):
            if ".staging." in str(src):
                raise OSError("Simulated staging -> active rename failure")
            if ".backup." in str(src):
                raise OSError("Simulated backup -> active rollback failure")
        return real_rename(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "rename", failing_commit_and_rollback)

    with pytest.raises(WorkspaceRollbackError) as excinfo:
        importer.import_archive(sandbox_id, valid_tar)

    assert excinfo.value.details.get("rollback_failed") is True
    assert excinfo.value.details.get("backup_preserved") is True

    # Verify backup was NOT deleted and staging WAS cleaned up
    backups = list(manager.base_dir.glob(f".backup.{sandbox_id}.*"))
    assert len(backups) == 1
    assert list(manager.base_dir.glob(f".staging.{sandbox_id}.*")) == []

    # Once filesystem recovers, the next read/write automatically restores the preserved backup
    monkeypatch.undo()
    assert manager.read_file(sandbox_id, "vital.txt").content == "only valid generation"
    assert list(manager.base_dir.glob(f".backup.{sandbox_id}.*")) == []


def test_recovery_from_interrupted_commit_crash_point_2(manager: WorkspaceManager):
    sandbox_id = "interrupted-commit-cp2"
    manager.write_file(sandbox_id, "recovered.txt", "state before crash")

    ws_path = manager.get_workspace_path(sandbox_id)
    backup_path = manager.base_dir / f".backup.{sandbox_id}.deadbeef"
    staging_path = manager.base_dir / f".staging.{sandbox_id}.deadbeef"

    # Crash Point 2: ws_path moved to backup_path, before staging_path was renamed to ws_path
    os.rename(ws_path, backup_path)
    staging_path.mkdir(mode=0o700)
    (staging_path / "partial.txt").write_text("incomplete")

    assert not ws_path.exists()
    assert backup_path.exists()

    # Next operation automatically recovers the backup under exclusive lock and cleans staging
    content = manager.read_file(sandbox_id, "recovered.txt")
    assert content.content == "state before crash"
    assert ws_path.exists()
    assert not backup_path.exists()
    assert not staging_path.exists()


def test_recovery_from_interrupted_commit_crash_point_3(manager: WorkspaceManager):
    sandbox_id = "interrupted-commit-cp3"
    manager.write_file(sandbox_id, "version.txt", "new committed version")

    ws_path = manager.get_workspace_path(sandbox_id)
    backup_path = manager.base_dir / f".backup.{sandbox_id}.oldgen"
    backup_path.mkdir(mode=0o700)
    (backup_path / "version.txt").write_text("old obsolete version")

    # Crash Point 3: new workspace is already active at ws_path, but old backup_path
    # still exists because process crashed before _remove_directory_tree(backup_path) finished.
    assert ws_path.exists()
    assert backup_path.exists()

    # Next operation must keep the new active workspace and delete the old backup
    content = manager.read_file(sandbox_id, "version.txt")
    assert content.content == "new committed version"
    assert ws_path.exists()
    assert not backup_path.exists()


def test_commit_and_recovery_base_dir_fsync_ordering(
    manager: WorkspaceManager,
    importer: SecureTarImporter,
    monkeypatch: pytest.MonkeyPatch,
):
    sandbox_id = "commit-fsync-order"
    manager.write_file(sandbox_id, "v.txt", "v1")

    events: list[str] = []
    real_rename = os.rename
    real_fsync = os.fsync
    base_stat = os.stat(manager.base_dir)

    def spy_rename(src, dst, *args, **kwargs):
        src_s, dst_s = str(src), str(dst)
        if ".backup." in dst_s:
            events.append("rename_active_to_backup")
        elif ".staging." in src_s:
            events.append("rename_staging_to_active")
        elif ".backup." in src_s:
            events.append("rename_backup_to_active")
        return real_rename(src, dst, *args, **kwargs)

    def spy_fsync(fd: int) -> None:
        st = os.fstat(fd)
        if os.path.samestat(st, base_stat):
            events.append("fsync_base_dir")
        real_fsync(fd)

    monkeypatch.setattr(os, "rename", spy_rename)
    monkeypatch.setattr(os, "fsync", spy_fsync)

    ti = tarfile.TarInfo("v.txt")
    importer.import_archive(sandbox_id, _build_tar_bytes([(ti, b"v2")]))

    # Verify ordering during commit:
    # rename_active_to_backup -> fsync_base_dir -> rename_staging_to_active -> fsync_base_dir
    idx_backup = events.index("rename_active_to_backup")
    idx_staging = events.index("rename_staging_to_active")
    assert events[idx_backup + 1] == "fsync_base_dir"
    assert events[idx_staging + 1] == "fsync_base_dir"

    # Now test recovery fsync ordering
    events.clear()
    ws_path = manager.get_workspace_path(sandbox_id)
    backup_path = manager.base_dir / f".backup.{sandbox_id}.rec"
    real_rename(ws_path, backup_path)

    assert manager.read_file(sandbox_id, "v.txt").content == "v2"
    idx_rec = events.index("rename_backup_to_active")
    assert events[idx_rec + 1] == "fsync_base_dir"


# ---------------------------------------------------------------------------
# Engine Synchronization Failure, Timeout vs APIError & Cleanup Unit Tests
# ---------------------------------------------------------------------------


def _make_mock_container(sandbox_id: str, settings: SandboxSettings) -> MagicMock:
    container = MagicMock()
    container.id = "c" * 64
    container.attrs = {
        "Config": {
            "Labels": {
                "project": settings.PROJECT_LABEL,
                "managed-by": settings.MANAGED_BY_LABEL,
                "sandbox_id": sandbox_id,
            }
        },
        "State": {"Running": False},
    }
    container.wait.return_value = {"StatusCode": 0}
    container.logs.side_effect = [iter([b"stdout ok\n"]), iter([b""])]
    return container


def test_engine_startup_failure_preserves_workspace_and_releases_lock(
    archive_settings: SandboxSettings,
    manager: WorkspaceManager,
):
    sandbox_id = "eng-start-fail"
    manager.write_file(sandbox_id, "state.txt", "preserved")

    client = MagicMock()
    client.containers.create.side_effect = DockerException("daemon failure")
    engine = EphemeralSandboxEngine(
        config=archive_settings,
        client=client,
        workspace_manager=manager,
    )

    with pytest.raises(DockerEngineError):
        engine.execute(ExecutionRequest(code="print(1)"), sandbox_id=sandbox_id)

    assert manager.read_file(sandbox_id, "state.txt").content == "preserved"
    # Verify lock and concurrency slot were released
    manager.write_file(sandbox_id, "state.txt", "updated after failure")
    assert manager.read_file(sandbox_id, "state.txt").content == "updated after failure"


def test_engine_distinguishes_timeout_from_docker_api_error(
    archive_settings: SandboxSettings,
    manager: WorkspaceManager,
):
    sandbox_id = "eng-timeout-vs-api"
    manager.write_file(sandbox_id, "safe.txt", "initial")

    # 1. Genuine ReadTimeout -> ExecutionStatus.TIMED_OUT
    client_timeout = MagicMock()
    c_timeout = _make_mock_container(sandbox_id, archive_settings)
    c_timeout.wait.side_effect = requests.exceptions.ReadTimeout("Read timed out.")
    client_timeout.containers.create.return_value = c_timeout

    engine_timeout = EphemeralSandboxEngine(
        config=archive_settings,
        client=client_timeout,
        workspace_manager=manager,
    )
    res_timeout = engine_timeout.execute(
        ExecutionRequest(code="while True: pass"),
        sandbox_id=sandbox_id,
    )
    assert res_timeout.status == ExecutionStatus.TIMED_OUT
    assert res_timeout.exit_code is None
    c_timeout.get_archive.assert_not_called()

    # 2. Non-timeout Docker APIError (e.g. HTTP 500 daemon fault) -> ExecutionStatus.ERROR
    client_err = MagicMock()
    c_err = _make_mock_container(sandbox_id, archive_settings)
    c_err.wait.side_effect = APIError("500 Server Error: Docker daemon internal fault")
    client_err.containers.create.return_value = c_err

    engine_err = EphemeralSandboxEngine(
        config=archive_settings,
        client=client_err,
        workspace_manager=manager,
    )
    res_err = engine_err.execute(
        ExecutionRequest(code="print(1)"),
        sandbox_id=sandbox_id,
    )
    assert res_err.status == ExecutionStatus.ERROR
    assert res_err.error_message == "Docker engine error during execution wait"
    c_err.get_archive.assert_not_called()
    assert manager.read_file(sandbox_id, "safe.txt").content == "initial"


def test_cleanup_verifies_container_stopped_before_removing_volumes(
    archive_settings: SandboxSettings,
    manager: WorkspaceManager,
):
    sandbox_id = "eng-stop-verify"
    manager.write_file(sandbox_id, "data.txt", "safe")

    # Case 1: Container is still running after kill(), stop(timeout=0) stops it ->
    # remove(v=True, force=True) succeeds
    client_ok = MagicMock()
    c_ok = _make_mock_container(sandbox_id, archive_settings)
    c_ok.attrs["State"] = {"Running": True}

    def stop_sets_not_running(**_kwargs):
        c_ok.attrs["State"] = {"Running": False}

    c_ok.stop.side_effect = stop_sets_not_running
    c_ok.get_archive.return_value = (_build_tar_bytes([]), {})
    client_ok.containers.create.return_value = c_ok

    engine_ok = EphemeralSandboxEngine(
        config=archive_settings,
        client=client_ok,
        workspace_manager=manager,
    )
    res = engine_ok.execute(ExecutionRequest(code="print('ok')"), sandbox_id=sandbox_id)
    assert res.status == ExecutionStatus.COMPLETED
    c_ok.stop.assert_called_once_with(timeout=0)
    c_ok.remove.assert_called_once_with(v=True, force=True)

    # Case 2: Container refuses to stop (State.Running remains True after kill and stop) ->
    # volume removal is NOT called, DockerEngineError is raised, workspace & lock preserved
    client_stuck = MagicMock()
    c_stuck = _make_mock_container(sandbox_id, archive_settings)
    c_stuck.attrs["State"] = {"Running": True}
    c_stuck.get_archive.return_value = (_build_tar_bytes([]), {})
    client_stuck.containers.create.return_value = c_stuck

    engine_stuck = EphemeralSandboxEngine(
        config=archive_settings,
        client=client_stuck,
        workspace_manager=manager,
    )
    with pytest.raises(DockerEngineError, match="Verified cleanup failed"):
        engine_stuck.execute(ExecutionRequest(code="print('stuck')"), sandbox_id=sandbox_id)

    c_stuck.remove.assert_not_called()
    # Workspace and lock remain intact and usable
    manager.write_file(sandbox_id, "data.txt", "still usable after cleanup failure")
    assert manager.read_file(sandbox_id, "data.txt").content == "still usable after cleanup failure"


def test_engine_archive_retrieval_failure_preserves_workspace(
    archive_settings: SandboxSettings,
    manager: WorkspaceManager,
):
    sandbox_id = "eng-get-archive-fail"
    manager.write_file(sandbox_id, "safe.txt", "before execution")

    client = MagicMock()
    container = _make_mock_container(sandbox_id, archive_settings)
    container.get_archive.side_effect = APIError("Failed to read archive from container")
    client.containers.create.return_value = container

    engine = EphemeralSandboxEngine(
        config=archive_settings,
        client=client,
        workspace_manager=manager,
    )
    result = engine.execute(ExecutionRequest(code="print('hi')"), sandbox_id=sandbox_id)

    assert result.status == ExecutionStatus.ERROR
    assert result.error_message is not None
    assert "unable to retrieve workspace archive" in result.error_message
    assert manager.read_file(sandbox_id, "safe.txt").content == "before execution"


def test_engine_archive_import_failure_preserves_workspace_and_sanitizes_error(
    archive_settings: SandboxSettings,
    manager: WorkspaceManager,
):
    sandbox_id = "eng-import-fail"
    manager.write_file(sandbox_id, "safe.txt", "before execution")

    # Malicious archive returned from container containing a symlink
    evil_ti = tarfile.TarInfo("workspace/evil_link")
    evil_ti.type = tarfile.SYMTYPE
    evil_ti.linkname = "/etc/passwd"
    evil_tar = _build_tar_bytes([(evil_ti, None)])

    client = MagicMock()
    container = _make_mock_container(sandbox_id, archive_settings)
    container.get_archive.return_value = ([evil_tar], {})
    client.containers.create.return_value = container

    engine = EphemeralSandboxEngine(
        config=archive_settings,
        client=client,
        workspace_manager=manager,
    )
    result = engine.execute(ExecutionRequest(code="print('hi')"), sandbox_id=sandbox_id)

    assert result.status == ExecutionStatus.ERROR
    assert result.error_message is not None
    assert "security policy" in result.error_message
    assert str(manager.base_dir) not in result.error_message
    assert manager.read_file(sandbox_id, "safe.txt").content == "before execution"


# ---------------------------------------------------------------------------
# Audit 5: Archive Snapshot Consistency Tests
# ---------------------------------------------------------------------------


def test_serializer_detects_file_inode_replacement_before_open(
    manager: WorkspaceManager,
    serializer: WorkspaceArchiveSerializer,
    monkeypatch: pytest.MonkeyPatch,
):
    sandbox_id = "ser-inode-mismatch"
    manager.write_file(sandbox_id, "target.txt", "same-size-12")
    target_path = manager.get_workspace_path(sandbox_id) / "target.txt"
    orig_ino = target_path.stat().st_ino

    real_fstat = os.fstat

    class _TamperedInoStat:
        def __init__(self, st: os.stat_result) -> None:
            self.st_mode = st.st_mode
            self.st_ino = st.st_ino + 123456
            self.st_dev = st.st_dev
            self.st_uid = st.st_uid
            self.st_size = st.st_size
            self.st_mtime = st.st_mtime
            self.st_mtime_ns = st.st_mtime_ns
            self.st_nlink = st.st_nlink

    def fstat_with_inode_swap(fd: int):
        st = real_fstat(fd)
        if st.st_ino == orig_ino:
            return _TamperedInoStat(st)
        return st

    monkeypatch.setattr(os, "fstat", fstat_with_inode_swap)

    with pytest.raises(PathTraversalError, match="inode/device identity changed"):
        serializer.serialize(sandbox_id)


def test_serializer_detects_file_mutation_during_streaming(
    manager: WorkspaceManager,
    serializer: WorkspaceArchiveSerializer,
    monkeypatch: pytest.MonkeyPatch,
):
    sandbox_id = "ser-stream-mutation"
    manager.write_file(sandbox_id, "mutating.txt", "initial-payload")
    target_path = manager.get_workspace_path(sandbox_id) / "mutating.txt"
    orig_ino = target_path.stat().st_ino

    real_fstat = os.fstat
    fstat_calls_for_target = 0

    class _MutatedMtimeStat:
        def __init__(self, st: os.stat_result) -> None:
            self.st_mode = st.st_mode
            self.st_ino = st.st_ino
            self.st_dev = st.st_dev
            self.st_uid = st.st_uid
            self.st_size = st.st_size
            self.st_mtime = st.st_mtime + 10
            self.st_mtime_ns = st.st_mtime_ns + 10_000_000_000
            self.st_nlink = st.st_nlink

    def fstat_mutated_after_read(fd: int):
        nonlocal fstat_calls_for_target
        st = real_fstat(fd)
        if st.st_ino == orig_ino:
            fstat_calls_for_target += 1
            # First fstat (before read) matches entry.stat(); second fstat (after read)
            # simulates concurrent modification while streaming.
            if fstat_calls_for_target >= 2:
                return _MutatedMtimeStat(st)
        return st

    monkeypatch.setattr(os, "fstat", fstat_mutated_after_read)

    with pytest.raises(PathTraversalError, match="Snapshot consistency violation"):
        serializer.serialize(sandbox_id)


def test_serializer_detects_directory_inode_replacement(
    manager: WorkspaceManager,
    serializer: WorkspaceArchiveSerializer,
    monkeypatch: pytest.MonkeyPatch,
):
    sandbox_id = "ser-dir-inode-mismatch"
    manager.write_file(sandbox_id, "pkg/mod.py", "x = 1")
    dir_ino = (manager.get_workspace_path(sandbox_id) / "pkg").stat().st_ino

    real_fstat = os.fstat

    class _TamperedDirStat:
        def __init__(self, st: os.stat_result) -> None:
            self.st_mode = st.st_mode
            self.st_ino = st.st_ino + 654321
            self.st_dev = st.st_dev
            self.st_uid = st.st_uid
            self.st_size = st.st_size
            self.st_mtime = st.st_mtime
            self.st_mtime_ns = st.st_mtime_ns
            self.st_nlink = st.st_nlink

    def fstat_dir_swap(fd: int):
        st = real_fstat(fd)
        if st.st_ino == dir_ino:
            return _TamperedDirStat(st)
        return st

    monkeypatch.setattr(os, "fstat", fstat_dir_swap)

    with pytest.raises(PathTraversalError, match="Directory identity changed"):
        serializer.serialize(sandbox_id)


# ---------------------------------------------------------------------------
# Audit 6 & Audit 7: Docker Cleanup Guarantees & Execution/Lifecycle Lock Lifetime
# ---------------------------------------------------------------------------


def test_cleanup_never_falls_back_to_remove_without_volumes(
    archive_settings: SandboxSettings,
    manager: WorkspaceManager,
):
    sandbox_id = "eng-no-volume-leak-fallback"
    manager.write_file(sandbox_id, "keep.txt", "safe")

    client = MagicMock()
    container = _make_mock_container(sandbox_id, archive_settings)
    container.get_archive.return_value = (_build_tar_bytes([]), {})
    # Simulate container.remove(v=True, force=True) raising TypeError or APIError
    container.remove.side_effect = TypeError("unexpected keyword argument 'v'")
    client.containers.create.return_value = container

    engine = EphemeralSandboxEngine(
        config=archive_settings,
        client=client,
        workspace_manager=manager,
    )

    with pytest.raises(DockerEngineError, match="Verified cleanup failed"):
        engine.execute(ExecutionRequest(code="print('test')"), sandbox_id=sandbox_id)

    # Must only have attempted remove(v=True, force=True) once — never remove(force=True)
    container.remove.assert_called_once_with(v=True, force=True)
    # Lock and concurrency slot must still be released
    assert manager._is_exclusive_lock_held(sandbox_id) is False
    assert engine._semaphore._value == archive_settings.GLOBAL_CONCURRENCY_LIMIT


def test_execution_holds_exclusive_workspace_lock_until_container_cleanup_completes(
    archive_settings: SandboxSettings,
    manager: WorkspaceManager,
):
    sandbox_id = "eng-lock-covers-cleanup"
    manager.write_file(sandbox_id, "data.txt", "v1")

    lock_held_during_remove: list[bool] = []
    client = MagicMock()
    container = _make_mock_container(sandbox_id, archive_settings)
    container.get_archive.return_value = (_build_tar_bytes([]), {})

    def verify_lock_on_remove(**kwargs):
        assert kwargs == {"v": True, "force": True}
        lock_held_during_remove.append(manager._is_exclusive_lock_held(sandbox_id))

    container.remove.side_effect = verify_lock_on_remove
    client.containers.create.return_value = container

    engine = EphemeralSandboxEngine(
        config=archive_settings,
        client=client,
        workspace_manager=manager,
    )
    res = engine.execute(ExecutionRequest(code="print('ok')"), sandbox_id=sandbox_id)
    assert res.status == ExecutionStatus.COMPLETED
    assert lock_held_during_remove == [True]
    assert manager._is_exclusive_lock_held(sandbox_id) is False

    # Also verify engine.cleanup_sandbox acquires the exclusive workspace lock
    lock_held_during_sandbox_cleanup: list[bool] = []
    c_orphan = _make_mock_container(sandbox_id, archive_settings)
    c_orphan.remove.side_effect = lambda **_kw: lock_held_during_sandbox_cleanup.append(
        manager._is_exclusive_lock_held(sandbox_id)
    )
    client.containers.list.return_value = [c_orphan]

    engine.cleanup_sandbox(sandbox_id)
    assert lock_held_during_sandbox_cleanup == [True]
    assert manager._is_exclusive_lock_held(sandbox_id) is False
