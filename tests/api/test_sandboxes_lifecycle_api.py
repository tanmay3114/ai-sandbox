"""Integration tests for Sandbox Lifecycle and Workspace File Management API & MCP."""

import base64
import json
import uuid
from contextlib import contextmanager
from datetime import timedelta

import docker
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.dependencies import get_sandbox_backend, get_settings
from app.core.config import SandboxSettings
from app.main import app
from app.mcp.server import create_mcp_server
from app.models.sandbox import Sandbox, utc_now
from app.sandbox.docker_client import list_sandbox_containers
from app.services.sandbox_lifecycle_service import SandboxLifecycleService


@pytest.fixture
def client() -> TestClient:
    """FastAPI TestClient fixture."""
    return TestClient(app)


def test_api_create_sandbox(client: TestClient):
    """Test POST /api/v1/sandboxes creates a new persistent sandbox session."""
    payload = {"runtime": "python", "ttl_seconds": 180}
    response = client.post("/api/v1/sandboxes", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert "sandbox_id" in data
    assert data["status"] == "running"
    assert data["runtime"] == "python"
    assert "created_at" in data
    assert "expires_at" in data
    assert data["destroyed_at"] is None


def test_api_create_sandbox_invalid_runtime(client: TestClient):
    """Test validation failure on unsupported runtime."""
    payload = {"runtime": "unsupported_ruby", "ttl_seconds": 180}
    response = client.post("/api/v1/sandboxes", json=payload)
    assert response.status_code == 422


def test_api_create_sandbox_invalid_ttl(client: TestClient):
    """Test validation failure on out-of-bounds TTL."""
    payload = {"runtime": "python", "ttl_seconds": 1}
    response = client.post("/api/v1/sandboxes", json=payload)
    assert response.status_code == 422


def test_api_get_sandbox(client: TestClient):
    """Test GET /api/v1/sandboxes/{sandbox_id}."""
    create_resp = client.post("/api/v1/sandboxes", json={"runtime": "python", "ttl_seconds": 180})
    sandbox_id = create_resp.json()["sandbox_id"]

    get_resp = client.get(f"/api/v1/sandboxes/{sandbox_id}")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["sandbox_id"] == sandbox_id
    assert data["status"] == "running"
    assert "resource_config" in data
    assert data["executions_count"] == 0


def test_api_get_sandbox_not_found(client: TestClient):
    """Test GET on unknown sandbox ID returns 404."""
    random_id = uuid.uuid4()
    response = client.get(f"/api/v1/sandboxes/{random_id}")
    assert response.status_code == 404
    data = response.json()
    assert data["error"] == "SandboxNotFoundError"


def test_api_delete_sandbox_idempotent(client: TestClient):
    """Test DELETE /api/v1/sandboxes/{sandbox_id} terminates and destroys session."""
    create_resp = client.post("/api/v1/sandboxes", json={"runtime": "python", "ttl_seconds": 180})
    sandbox_id = create_resp.json()["sandbox_id"]

    del_resp1 = client.delete(f"/api/v1/sandboxes/{sandbox_id}")
    assert del_resp1.status_code == 200
    assert del_resp1.json()["status"] == "destroyed"

    # Repeated deletion should be idempotent and return 200
    del_resp2 = client.delete(f"/api/v1/sandboxes/{sandbox_id}")
    assert del_resp2.status_code == 200
    assert del_resp2.json()["status"] == "destroyed"


def test_api_execute_in_sandbox(client: TestClient):
    """Test POST /api/v1/sandboxes/{sandbox_id}/execute runs code and records history."""
    create_resp = client.post("/api/v1/sandboxes", json={"runtime": "python", "ttl_seconds": 180})
    sandbox_id = create_resp.json()["sandbox_id"]

    exec_payload = {"code": "print(10 * 10)"}
    exec_resp = client.post(f"/api/v1/sandboxes/{sandbox_id}/execute", json=exec_payload)

    assert exec_resp.status_code == 200
    data = exec_resp.json()
    assert data["sandbox_id"] == sandbox_id
    assert data["status"] == "completed"
    assert data["exit_code"] == 0
    assert data["stdout"].strip() == "100"
    assert "execution_id" in data
    assert data["submitted_at"] is not None
    assert data["completed_at"] is not None

    # Check that execution count incremented in get_sandbox
    get_resp = client.get(f"/api/v1/sandboxes/{sandbox_id}")
    assert get_resp.json()["executions_count"] == 1


def test_api_execute_on_destroyed_sandbox_fails(client: TestClient):
    """Test executing code on a destroyed sandbox returns 400."""
    create_resp = client.post("/api/v1/sandboxes", json={"runtime": "python", "ttl_seconds": 180})
    sandbox_id = create_resp.json()["sandbox_id"]

    client.delete(f"/api/v1/sandboxes/{sandbox_id}")

    exec_resp = client.post(
        f"/api/v1/sandboxes/{sandbox_id}/execute",
        json={"code": "print('fail')"},
    )
    assert exec_resp.status_code == 400
    data = exec_resp.json()
    assert data["error"] == "SandboxDestroyedError"


def test_api_execute_on_unknown_sandbox_returns_404(client: TestClient):
    """Test executing on a non-existent sandbox returns 404."""
    random_id = uuid.uuid4()
    response = client.post(f"/api/v1/sandboxes/{random_id}/execute", json={"code": "print('fail')"})
    assert response.status_code == 404
    assert response.json()["error"] == "SandboxNotFoundError"


def test_api_get_execution_result_success(client: TestClient):
    """Test GET /api/v1/sandboxes/{sandbox_id}/executions/{execution_id}."""
    create_resp = client.post("/api/v1/sandboxes", json={"runtime": "python", "ttl_seconds": 180})
    sandbox_id = create_resp.json()["sandbox_id"]

    exec_resp = client.post(
        f"/api/v1/sandboxes/{sandbox_id}/execute",
        json={"code": "print('API job lookup')"},
    )
    assert exec_resp.status_code == 200
    execution_id = exec_resp.json()["execution_id"]

    get_exec_resp = client.get(f"/api/v1/sandboxes/{sandbox_id}/executions/{execution_id}")
    assert get_exec_resp.status_code == 200
    data = get_exec_resp.json()
    assert data["execution_id"] == execution_id
    assert data["sandbox_id"] == sandbox_id
    assert data["status"] == "completed"
    assert "API job lookup" in data["stdout"]
    assert data["exit_code"] == 0


def test_api_get_execution_result_not_found(client: TestClient):
    """Test GET on unknown execution ID returns 404 ExecutionNotFoundError."""
    create_resp = client.post("/api/v1/sandboxes", json={"runtime": "python", "ttl_seconds": 180})
    sandbox_id = create_resp.json()["sandbox_id"]
    random_exec_id = uuid.uuid4()

    response = client.get(f"/api/v1/sandboxes/{sandbox_id}/executions/{random_exec_id}")
    assert response.status_code == 404
    assert response.json()["error"] == "ExecutionNotFoundError"


def test_api_get_execution_result_mismatched_sandbox(client: TestClient):
    """Test GET execution under a different sandbox ID returns 404 ExecutionNotFoundError."""
    s1_resp = client.post("/api/v1/sandboxes", json={"runtime": "python", "ttl_seconds": 180})
    sandbox1_id = s1_resp.json()["sandbox_id"]
    s2_resp = client.post("/api/v1/sandboxes", json={"runtime": "python", "ttl_seconds": 180})
    sandbox2_id = s2_resp.json()["sandbox_id"]

    exec_resp = client.post(
        f"/api/v1/sandboxes/{sandbox1_id}/execute",
        json={"code": "print('s1')"},
    )
    execution_id = exec_resp.json()["execution_id"]

    # Attempt fetching sandbox 1's execution under sandbox 2
    response = client.get(f"/api/v1/sandboxes/{sandbox2_id}/executions/{execution_id}")
    assert response.status_code == 404
    assert response.json()["error"] == "ExecutionNotFoundError"


# =====================================================================
# Phase 2 Steps 4 & 5: End-to-End API + MCP + Execution Verification
# =====================================================================


def _make_live_mcp_server(db_session: Session):
    """Create an MCPServer wired to the same backend and DB as the FastAPI TestClient."""

    @contextmanager
    def service_factory():
        yield SandboxLifecycleService(
            db=db_session,
            backend=get_sandbox_backend(),
            config=get_settings(),
        )

    return create_mcp_server(service_factory=service_factory)


def _mcp_json(result) -> dict:
    assert result is not None
    assert len(result.content) > 0
    return json.loads(result.content[0].text)


@pytest.mark.asyncio
async def test_e2e_complete_persistence_workflow_api_mcp_docker(
    client: TestClient,
    db_session: Session,
    docker_client: docker.DockerClient,
):
    """Step 5A & 5B: Verify 14-step end-to-end API <-> MCP <-> Docker persistence workflow."""
    mcp_server = _make_live_mcp_server(db_session)
    config = get_settings()
    volumes_before = {v.name for v in docker_client.volumes.list()}

    # 1. Create a sandbox
    create_resp = client.post("/api/v1/sandboxes", json={"runtime": "python", "ttl_seconds": 180})
    assert create_resp.status_code == 201
    sandbox_id = create_resp.json()["sandbox_id"]

    # 2. Write a file through the API
    write_resp = client.post(
        f"/api/v1/sandboxes/{sandbox_id}/files",
        json={"path": "notes.txt", "content": "initial-from-api\n", "encoding": "utf-8"},
    )
    assert write_resp.status_code == 200
    assert write_resp.json()["path"] == "notes.txt"
    assert write_resp.json()["size_bytes"] == len("initial-from-api\n")
    assert write_resp.json()["is_directory"] is False

    # 3. Read it through MCP (API write -> MCP read)
    mcp_read1 = _mcp_json(
        await mcp_server.call_tool("read_file", {"sandbox_id": sandbox_id, "path": "notes.txt"})
    )
    assert mcp_read1["path"] == "notes.txt"
    assert mcp_read1["content"] == "initial-from-api\n"
    assert mcp_read1["encoding"] == "utf-8"

    # Also verify MCP write -> API read
    mcp_write = _mcp_json(
        await mcp_server.call_tool(
            "write_file",
            {
                "sandbox_id": sandbox_id,
                "path": "mcp_created.txt",
                "content": "written-via-mcp",
                "encoding": "utf-8",
            },
        )
    )
    assert mcp_write["path"] == "mcp_created.txt"
    api_read_mcp = client.get(f"/api/v1/sandboxes/{sandbox_id}/files/mcp_created.txt")
    assert api_read_mcp.status_code == 200
    assert api_read_mcp.json()["content"] == "written-via-mcp"

    # 4. List workspace contents (via API and MCP)
    list_resp1 = client.get(f"/api/v1/sandboxes/{sandbox_id}/files")
    assert list_resp1.status_code == 200
    listed_paths1 = {f["path"] for f in list_resp1.json()["files"]}
    assert listed_paths1 == {"notes.txt", "mcp_created.txt"}

    mcp_list1 = _mcp_json(
        await mcp_server.call_tool("list_files", {"sandbox_id": sandbox_id, "path": ""})
    )
    assert {f["path"] for f in mcp_list1["files"]} == {"notes.txt", "mcp_created.txt"}

    # 5. Execute code that reads the file (API write -> Docker execution)
    exec_read = client.post(
        f"/api/v1/sandboxes/{sandbox_id}/execute",
        json={"code": "print(open('notes.txt').read().strip())"},
    )
    assert exec_read.status_code == 200
    assert exec_read.json()["status"] == "completed"
    assert exec_read.json()["stdout"].strip() == "initial-from-api"

    # 6. Execute code that modifies the file and creates a new file in /workspace
    exec_modify = client.post(
        f"/api/v1/sandboxes/{sandbox_id}/execute",
        json={
            "code": (
                "with open('notes.txt', 'a') as f:\n"
                "    f.write('modified-in-docker\\n')\n"
                "with open('from_docker.txt', 'w') as f:\n"
                "    f.write('created-by-container')\n"
            )
        },
    )
    assert exec_modify.status_code == 200
    assert exec_modify.json()["status"] == "completed"

    # 7. Read the modified file through the API (and Docker write -> API & MCP read)
    read_modified = client.get(f"/api/v1/sandboxes/{sandbox_id}/files/notes.txt")
    assert read_modified.status_code == 200
    assert read_modified.json()["content"] == "initial-from-api\nmodified-in-docker\n"

    read_docker_api = client.get(f"/api/v1/sandboxes/{sandbox_id}/files/from_docker.txt")
    assert read_docker_api.status_code == 200
    assert read_docker_api.json()["content"] == "created-by-container"

    read_docker_mcp = _mcp_json(
        await mcp_server.call_tool(
            "read_file", {"sandbox_id": sandbox_id, "path": "from_docker.txt"}
        )
    )
    assert read_docker_mcp["content"] == "created-by-container"

    # 8. Create a directory (via API and nested via MCP)
    mkdir_resp = client.post(
        f"/api/v1/sandboxes/{sandbox_id}/directories",
        json={"path": "reports/daily"},
    )
    assert mkdir_resp.status_code == 200
    assert mkdir_resp.json() == {"path": "reports/daily", "created": True}

    # 9. Create another file inside that directory
    nested_write = client.post(
        f"/api/v1/sandboxes/{sandbox_id}/files",
        json={"path": "reports/daily/summary.txt", "content": "all-green", "encoding": "utf-8"},
    )
    assert nested_write.status_code == 200
    assert nested_write.json()["path"] == "reports/daily/summary.txt"

    # 10. Delete a file (via API and via MCP)
    del_resp = client.delete(f"/api/v1/sandboxes/{sandbox_id}/files/mcp_created.txt")
    assert del_resp.status_code == 200
    assert del_resp.json() == {"path": "mcp_created.txt", "deleted": True}

    mcp_del = _mcp_json(
        await mcp_server.call_tool(
            "delete_file", {"sandbox_id": sandbox_id, "path": "from_docker.txt"}
        )
    )
    assert mcp_del == {"path": "from_docker.txt", "deleted": True}

    # 11. Verify the remaining workspace contents
    list_final = client.get(f"/api/v1/sandboxes/{sandbox_id}/files")
    assert list_final.status_code == 200
    remaining_paths = {f["path"] for f in list_final.json()["files"]}
    assert "mcp_created.txt" not in remaining_paths
    assert "from_docker.txt" not in remaining_paths
    assert {"notes.txt", "reports", "reports/daily", "reports/daily/summary.txt"} <= remaining_paths

    # 12. Destroy the sandbox
    destroy_resp = client.delete(f"/api/v1/sandboxes/{sandbox_id}")
    assert destroy_resp.status_code == 200
    assert destroy_resp.json()["status"] == "destroyed"

    # 13. Verify the persistent workspace has been deleted
    assert not (config.WORKSPACE_DIR / sandbox_id).exists()
    assert list(config.WORKSPACE_DIR.glob(f"*{sandbox_id}*")) == []

    # 14. Verify no execution containers or anonymous volumes remain
    assert list_sandbox_containers(docker_client, config=config, all_states=True) == []
    volumes_after = {v.name for v in docker_client.volumes.list()}
    assert volumes_after - volumes_before == set()


@pytest.mark.asyncio
async def test_workspace_security_and_isolation_across_api_and_mcp(
    client: TestClient,
    db_session: Session,
):
    """Step 5C: Verify cross-sandbox isolation, lifecycle guards, traversal, and quotas."""
    mcp_server = _make_live_mcp_server(db_session)
    config = get_settings()
    host_ws_str = str(config.WORKSPACE_DIR)

    # Create two sandboxes (Sandbox A and Sandbox B)
    s_a = client.post("/api/v1/sandboxes", json={"runtime": "python", "ttl_seconds": 180}).json()[
        "sandbox_id"
    ]
    s_b = client.post("/api/v1/sandboxes", json={"runtime": "python", "ttl_seconds": 180}).json()[
        "sandbox_id"
    ]

    # Write secret file in Sandbox A
    w_a = client.post(
        f"/api/v1/sandboxes/{s_a}/files",
        json={"path": "secret.txt", "content": "only-for-sandbox-a"},
    )
    assert w_a.status_code == 200

    # 1. Cross-sandbox isolation: Sandbox B cannot read, list, or delete Sandbox A's files
    read_b = client.get(f"/api/v1/sandboxes/{s_b}/files/secret.txt")
    assert read_b.status_code == 404
    assert read_b.json()["error"] == "SandboxFileNotFoundError"
    assert host_ws_str not in read_b.text

    traverse_b_to_a = client.post(
        f"/api/v1/sandboxes/{s_b}/files",
        json={"path": f"../{s_a}/pwned.txt", "content": "escape"},
    )
    assert traverse_b_to_a.status_code == 400
    assert traverse_b_to_a.json()["error"] == "PathTraversalError"
    assert host_ws_str not in traverse_b_to_a.text

    mcp_traverse = _mcp_json(
        await mcp_server.call_tool(
            "read_file",
            {"sandbox_id": s_b, "path": f"../{s_a}/secret.txt"},
        )
    )
    assert mcp_traverse["error"] == "PathTraversalError"
    assert host_ws_str not in json.dumps(mcp_traverse)

    # 2. Path traversal and absolute path rejection on API and MCP
    for bad_path in ["../escape.txt", "sub/../../escape.txt", "/etc/passwd", "a\\b.txt"]:
        resp_w = client.post(
            f"/api/v1/sandboxes/{s_a}/files",
            json={"path": bad_path, "content": "bad"},
        )
        assert resp_w.status_code == 400
        assert resp_w.json()["error"] == "PathTraversalError"
        assert host_ws_str not in resp_w.text

        resp_d = client.post(
            f"/api/v1/sandboxes/{s_a}/directories",
            json={"path": bad_path},
        )
        assert resp_d.status_code == 400
        assert resp_d.json()["error"] == "PathTraversalError"

        resp_del = client.delete(
            f"/api/v1/sandboxes/{s_a}/files",
            params={"path": bad_path},
        )
        assert resp_del.status_code == 400
        assert resp_del.json()["error"] == "PathTraversalError"

        mcp_bad = _mcp_json(
            await mcp_server.call_tool(
                "write_file",
                {"sandbox_id": s_a, "path": bad_path, "content": "bad"},
            )
        )
        assert mcp_bad["error"] == "PathTraversalError"
        assert host_ws_str not in json.dumps(mcp_bad)

    # 3. Invalid encodings handled safely (both unsupported encoding name and invalid base64)
    bad_enc_resp = client.post(
        f"/api/v1/sandboxes/{s_a}/files",
        json={"path": "enc.txt", "content": "abc", "encoding": "utf-16"},
    )
    assert bad_enc_resp.status_code == 400
    assert bad_enc_resp.json()["error"] == "InvalidFileEncodingError"

    bad_b64_resp = client.post(
        f"/api/v1/sandboxes/{s_a}/files",
        json={"path": "enc.bin", "content": "!!!not-valid-base64!!!", "encoding": "base64"},
    )
    assert bad_b64_resp.status_code == 400
    assert bad_b64_resp.json()["error"] == "InvalidFileEncodingError"

    mcp_bad_b64 = _mcp_json(
        await mcp_server.call_tool(
            "write_file",
            {
                "sandbox_id": s_a,
                "path": "enc.bin",
                "content": "!!!not-valid-base64!!!",
                "encoding": "base64",
            },
        )
    )
    assert mcp_bad_b64["error"] == "InvalidFileEncodingError"

    # Valid base64 binary round-trip via API and MCP
    raw_bytes = b"\x00\x01\xfe\xffbinary-payload"
    b64_str = base64.b64encode(raw_bytes).decode("ascii")
    ok_b64 = client.post(
        f"/api/v1/sandboxes/{s_a}/files",
        json={"path": "binary.bin", "content": b64_str, "encoding": "base64"},
    )
    assert ok_b64.status_code == 200
    assert ok_b64.json()["size_bytes"] == len(raw_bytes)
    read_b64 = client.get(f"/api/v1/sandboxes/{s_a}/files/binary.bin")
    assert read_b64.status_code == 200
    assert read_b64.json()["encoding"] == "base64"
    assert base64.b64decode(read_b64.json()["content"]) == raw_bytes

    # 4. Expired sandbox rejects all workspace operations across API and MCP
    s_b_row = db_session.get(Sandbox, uuid.UUID(s_b))
    assert s_b_row is not None
    s_b_row.expires_at = utc_now() - timedelta(seconds=10)
    db_session.commit()

    exp_api = client.post(
        f"/api/v1/sandboxes/{s_b}/files",
        json={"path": "late.txt", "content": "too-late"},
    )
    assert exp_api.status_code == 400
    assert exp_api.json()["error"] == "SandboxExpiredError"

    exp_mcp = _mcp_json(
        await mcp_server.call_tool(
            "list_files",
            {"sandbox_id": s_b, "path": ""},
        )
    )
    assert exp_mcp["error"] == "SandboxExpiredError"

    # 5. Destroyed sandbox rejects all workspace operations across API and MCP
    client.delete(f"/api/v1/sandboxes/{s_a}")
    dest_api = client.get(f"/api/v1/sandboxes/{s_a}/files/secret.txt")
    assert dest_api.status_code == 400
    assert dest_api.json()["error"] == "SandboxDestroyedError"

    dest_mcp = _mcp_json(
        await mcp_server.call_tool(
            "write_file",
            {"sandbox_id": s_a, "path": "revive.txt", "content": "no"},
        )
    )
    assert dest_mcp["error"] == "SandboxDestroyedError"
    assert not (config.WORKSPACE_DIR / s_a).exists()


@pytest.mark.asyncio
async def test_workspace_oversized_payload_rejected_across_api_and_mcp(
    db_session: Session,
    fast_settings: SandboxSettings,
    tmp_path,
):
    """Step 5C: Verify oversized file payloads are rejected with FileQuotaExceededError."""
    from app.sandbox.factory import create_sandbox_backend

    small_quota_settings = fast_settings.model_copy(
        update={
            "WORKSPACE_DIR": tmp_path / "ws_quota_api",
            "MAX_FILE_SIZE_BYTES": 64,
        }
    )
    small_backend = create_sandbox_backend(config=small_quota_settings)
    app.dependency_overrides[get_settings] = lambda: small_quota_settings
    app.dependency_overrides[get_sandbox_backend] = lambda: small_backend
    try:
        with TestClient(app) as quota_client:

            @contextmanager
            def quota_service_factory():
                yield SandboxLifecycleService(
                    db=db_session,
                    backend=small_backend,
                    config=small_quota_settings,
                )

            mcp_server = create_mcp_server(service_factory=quota_service_factory)
            s_id = quota_client.post(
                "/api/v1/sandboxes", json={"runtime": "python", "ttl_seconds": 180}
            ).json()["sandbox_id"]

            oversized = "X" * 128
            api_resp = quota_client.post(
                f"/api/v1/sandboxes/{s_id}/files",
                json={"path": "big.txt", "content": oversized},
            )
            assert api_resp.status_code == 400
            assert api_resp.json()["error"] == "FileQuotaExceededError"
            assert str(small_quota_settings.WORKSPACE_DIR) not in api_resp.text

            mcp_resp = _mcp_json(
                await mcp_server.call_tool(
                    "write_file",
                    {"sandbox_id": s_id, "path": "big.txt", "content": oversized},
                )
            )
            assert mcp_resp["error"] == "FileQuotaExceededError"

            quota_client.delete(f"/api/v1/sandboxes/{s_id}")
    finally:
        app.dependency_overrides.clear()
