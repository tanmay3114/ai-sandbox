"""Security and hardening isolation verification tests.

Verifies Docker Engine configuration and runtime confinement properties.
"""

import docker

from app.core.config import SandboxSettings
from app.sandbox.docker_client import cleanup_container_safely
from app.sandbox.engine import EphemeralSandboxEngine
from app.sandbox.schemas import ExecutionStatus
from app.sandbox.security import build_container_parameters


def test_docker_host_config_security_attributes(
    docker_client: docker.DockerClient,
    fast_settings: SandboxSettings,
):
    """Inspect actual Docker HostConfig and Config to verify security hardening."""
    params = build_container_parameters(
        code="pass",
        sandbox_id="sec-audit-test",
        config=fast_settings,
    )
    container = docker_client.containers.run(**params)
    try:
        container.reload()
        hc = container.attrs["HostConfig"]
        cfg = container.attrs["Config"]

        # 1. No privileged mode
        assert hc["Privileged"] is False, "Privileged mode MUST be disabled"

        # 2. Dropped capabilities
        assert hc["CapDrop"] == ["ALL"], "ALL Linux capabilities MUST be dropped"

        # 3. No new privileges
        assert "no-new-privileges:true" in hc["SecurityOpt"], "no-new-privileges MUST be enabled"

        # 4. Network disabled
        assert hc["NetworkMode"] == "none", "Network mode MUST be none"

        # 5. Non-root execution
        assert cfg["User"] == "10001:10001", "User MUST be non-root UID 10001"

        # 6. Read-only root filesystem
        assert hc["ReadonlyRootfs"] is True, "Root filesystem MUST be read-only"

        # 7. Bounded tmpfs
        assert "/tmp" in hc["Tmpfs"], "/tmp MUST be mounted as tmpfs"
        assert "noexec" in hc["Tmpfs"]["/tmp"], "tmpfs MUST include noexec flag"

        # 8. No host mounts or volume binds
        assert hc.get("Binds") is None or hc.get("Binds") == [], "Host mounts MUST NOT exist"

        # 9. Resource limits
        assert hc["PidsLimit"] == fast_settings.PIDS_LIMIT, "PID limit must match settings"
        assert hc["Memory"] == 134217728, "Memory limit must match 128m in test settings"
        assert hc["NanoCpus"] == 500_000_000, "NanoCpus must be 0.5 core"

        # 10. Labels
        assert cfg["Labels"]["project"] == "ai-sandbox"
        assert cfg["Labels"]["managed-by"] == "ai-sandbox-platform"
        assert cfg["Labels"]["sandbox_id"] == "sec-audit-test"

    finally:
        cleanup_container_safely(container, sandbox_id="sec-audit-test")


def test_network_isolation_runtime(engine: EphemeralSandboxEngine):
    """Verify that network connections are blocked by the kernel inside the container."""
    code = """
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(1)
try:
    s.connect(('1.1.1.1', 80))
    print('NETWORK_ACCESSIBLE')
except Exception as e:
    print(f'NETWORK_BLOCKED: {type(e).__name__}')
"""
    result = engine.execute(code)
    assert result.status == ExecutionStatus.COMPLETED
    assert "NETWORK_BLOCKED" in result.stdout
    assert "NETWORK_ACCESSIBLE" not in result.stdout


def test_filesystem_read_only_root_runtime(engine: EphemeralSandboxEngine):
    """Verify that attempting to write to the root filesystem fails with Read-only error."""
    code = """
try:
    with open('/malicious_file.txt', 'w') as f:
        f.write('pwned')
    print('WRITE_SUCCEEDED')
except OSError as e:
    print(f'READONLY_ENFORCED: {type(e).__name__}')
"""
    result = engine.execute(code)
    assert result.status == ExecutionStatus.COMPLETED
    assert "READONLY_ENFORCED" in result.stdout
    assert "WRITE_SUCCEEDED" not in result.stdout


def test_tmpfs_writable_workspace_runtime(engine: EphemeralSandboxEngine):
    """Verify that /tmp is writable via the tmpfs mount."""
    code = """
with open('/tmp/test_workspace.txt', 'w') as f:
    f.write('temporary data')

with open('/tmp/test_workspace.txt', 'r') as f:
    print('TMP_READ:', f.read())
"""
    result = engine.execute(code)
    assert result.status == ExecutionStatus.COMPLETED
    assert "TMP_READ: temporary data" in result.stdout


def test_unprivileged_uid_runtime(engine: EphemeralSandboxEngine):
    """Verify execution runs as non-root UID 10001."""
    code = """
import os
print(f"UID={os.getuid()}, GID={os.getgid()}")
"""
    result = engine.execute(code)
    assert result.status == ExecutionStatus.COMPLETED
    assert "UID=10001, GID=10001" in result.stdout


def test_docker_socket_not_accessible_runtime(engine: EphemeralSandboxEngine):
    """Verify that /var/run/docker.sock does not exist inside the sandbox."""
    code = """
import os
sock_exists = os.path.exists('/var/run/docker.sock')
print(f"DOCKER_SOCK_EXISTS={sock_exists}")
"""
    result = engine.execute(code)
    assert result.status == ExecutionStatus.COMPLETED
    assert "DOCKER_SOCK_EXISTS=False" in result.stdout
