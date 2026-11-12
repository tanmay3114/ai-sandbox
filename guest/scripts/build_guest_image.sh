#!/usr/bin/env bash
# Reproducible ARM64 Linux Guest Image Builder for AI Sandbox (Phase 3)
#
# Builds the immutable ARM64 Linux guest assets used by QemuSandboxBackend:
#   - .sandboxes/qemu/images/vmlinuz-virt     (Alpine Linux 3.21 aarch64 virt kernel)
#   - .sandboxes/qemu/images/initramfs-virt   (Compressed cpio initramfs with Python 3 + guest_agent.py)
#   - .sandboxes/qemu/images/rootfs.qcow2     (Immutable base qcow2 disk image)
#   - .sandboxes/qemu/images/manifest.json    (SHA-256 digests and provenance metadata)
#
# All downloaded upstream artifacts are verified against pinned SHA-256 digests
# before unpacking. Guest image provisioning is strictly separate from FastAPI
# runtime startup.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
OUTPUT_DIR="${SANDBOX_QEMU_IMAGE_DIR:-${REPO_ROOT}/.sandboxes/qemu/images}"
CACHE_DIR="${REPO_ROOT}/.sandboxes/qemu/cache"

# Pinned Alpine Linux 3.21.3 aarch64 release artifacts
ALPINE_BRANCH="v3.21"
ALPINE_VERSION="3.21.3"
ALPINE_ARCH="aarch64"

MINIROOTFS_TARBALL="alpine-minirootfs-${ALPINE_VERSION}-${ALPINE_ARCH}.tar.gz"
MINIROOTFS_URL="https://dl-cdn.alpinelinux.org/alpine/${ALPINE_BRANCH}/releases/${ALPINE_ARCH}/${MINIROOTFS_TARBALL}"

NETBOOT_TARBALL="alpine-netboot-${ALPINE_VERSION}-${ALPINE_ARCH}.tar.gz"
NETBOOT_URL="https://dl-cdn.alpinelinux.org/alpine/${ALPINE_BRANCH}/releases/${ALPINE_ARCH}/${NETBOOT_TARBALL}"

# Trusted SHA-256 pins. These MUST be copied from Alpine's official release
# checksum files (<artifact>.sha256, GPG-verifiable via <artifact>.asc) and the
# builder image digest from `docker buildx imagetools inspect alpine:3.21`.
# They are deliberately NOT hardcoded here because they were not verifiable
# from the development sandbox; the build fails closed until they are set.
PINS_FILE="${SCRIPT_DIR}/guest_image_pins.env"
if [[ -f "${PINS_FILE}" ]]; then
    # shellcheck source=/dev/null
    source "${PINS_FILE}"
fi
MINIROOTFS_SHA256="${MINIROOTFS_SHA256:-}"
NETBOOT_SHA256="${NETBOOT_SHA256:-}"
ALPINE_CONTAINER_IMAGE="${ALPINE_CONTAINER_IMAGE:-}"

for pin_name in MINIROOTFS_SHA256 NETBOOT_SHA256; do
    pin_value="${!pin_name}"
    if [[ ! "${pin_value}" =~ ^[0-9a-f]{64}$ ]]; then
        echo "ERROR: ${pin_name} is not set to a 64-hex SHA-256 digest." >&2
        echo "Copy it from ${MINIROOTFS_URL%/*}/<artifact>.sha256 into ${PINS_FILE}." >&2
        exit 1
    fi
done
if [[ ! "${ALPINE_CONTAINER_IMAGE}" =~ ^alpine@sha256:[0-9a-f]{64}$ ]]; then
    echo "ERROR: ALPINE_CONTAINER_IMAGE must be a digest-pinned reference (alpine@sha256:...)." >&2
    exit 1
fi

verify_sha256() {
    local file_path="$1"
    local expected_hash="$2"
    local actual_hash
    actual_hash="$(shasum -a 256 "${file_path}" | awk '{print $1}')"
    if [[ "${actual_hash}" != "${expected_hash}" ]]; then
        echo "ERROR: SHA-256 mismatch for ${file_path}" >&2
        echo "  Expected: ${expected_hash}" >&2
        echo "  Actual:   ${actual_hash}" >&2
        rm -f "${file_path}"
        exit 1
    fi
}

mkdir -p "${OUTPUT_DIR}" "${CACHE_DIR}"
chmod 0700 "${REPO_ROOT}/.sandboxes/qemu" 2>/dev/null || true

if ! command -v qemu-img >/dev/null 2>&1; then
    echo "ERROR: 'qemu-img' is required to build the guest qcow2 base image." >&2
    echo "Install QEMU on macOS ARM64 first: brew install qemu" >&2
    exit 1
fi

echo "==> [1/4] Verifying / fetching pinned Alpine ${ALPINE_VERSION} (${ALPINE_ARCH}) artifacts..."
if [[ ! -f "${CACHE_DIR}/${NETBOOT_TARBALL}" ]]; then
    curl -fsSL "${NETBOOT_URL}" -o "${CACHE_DIR}/${NETBOOT_TARBALL}"
fi
verify_sha256 "${CACHE_DIR}/${NETBOOT_TARBALL}" "${NETBOOT_SHA256}"

if [[ ! -f "${CACHE_DIR}/${MINIROOTFS_TARBALL}" ]]; then
    curl -fsSL "${MINIROOTFS_URL}" -o "${CACHE_DIR}/${MINIROOTFS_TARBALL}"
fi
verify_sha256 "${CACHE_DIR}/${MINIROOTFS_TARBALL}" "${MINIROOTFS_SHA256}"

WORK_DIR="$(mktemp -d "${CACHE_DIR}/build.XXXXXX")"
trap 'rm -rf "${WORK_DIR}"' EXIT

echo "==> [2/4] Extracting ARM64 vmlinuz-virt kernel..."
tar -xzf "${CACHE_DIR}/${NETBOOT_TARBALL}" -C "${WORK_DIR}" boot/vmlinuz-virt boot/modloop-virt
cp "${WORK_DIR}/boot/vmlinuz-virt" "${OUTPUT_DIR}/vmlinuz-virt"
chmod 0644 "${OUTPUT_DIR}/vmlinuz-virt"

echo "==> [3/4] Building ARM64 initramfs with Python 3, UID/GID 10001, and guest_agent.py..."
docker run --rm --platform linux/arm64 \
    -v "${CACHE_DIR}/${MINIROOTFS_TARBALL}:/in/minirootfs.tar.gz:ro" \
    -v "${REPO_ROOT}/guest/agent/guest_agent.py:/in/guest_agent.py:ro" \
    -v "${REPO_ROOT}/guest/system/init:/in/init:ro" \
    -v "${OUTPUT_DIR}:/out" \
    "${ALPINE_CONTAINER_IMAGE}" \
    /bin/sh -euxc '
        apk add --no-cache cpio gzip
        mkdir -p /rootfs
        tar -xzf /in/minirootfs.tar.gz -C /rootfs
        cp /etc/resolv.conf /rootfs/etc/resolv.conf
        chroot /rootfs /sbin/apk add --no-cache python3
        rm -f /rootfs/etc/resolv.conf
        chroot /rootfs /usr/sbin/addgroup -g 10001 -S sandbox || true
        chroot /rootfs /usr/sbin/adduser -u 10001 -G sandbox -h /workspace -s /sbin/nologin -D -H sandbox || true
        mkdir -p /rootfs/opt/aisandbox /rootfs/workspace
        cp /in/guest_agent.py /rootfs/opt/aisandbox/guest_agent.py
        chown 0:0 /rootfs/opt/aisandbox/guest_agent.py
        chmod 0700 /rootfs/opt/aisandbox/guest_agent.py
        cp /in/init /rootfs/init
        chown 0:0 /rootfs/init
        chmod 0755 /rootfs/init
        chown 10001:10001 /rootfs/workspace
        chmod 0700 /rootfs/workspace
        (cd /rootfs && find . -print0 | cpio --null -o -H newc | gzip -9 > /out/initramfs-virt)
        chmod 0644 /out/initramfs-virt
    '

echo "==> [4/4] Creating immutable base qcow2 disk and SHA-256 manifest..."
qemu-img create -f qcow2 "${OUTPUT_DIR}/rootfs.qcow2" 512M >/dev/null
chmod 0644 "${OUTPUT_DIR}/rootfs.qcow2"

KERNEL_HASH="$(shasum -a 256 "${OUTPUT_DIR}/vmlinuz-virt" | awk '{print $1}')"
INITRD_HASH="$(shasum -a 256 "${OUTPUT_DIR}/initramfs-virt" | awk '{print $1}')"
ROOTFS_HASH="$(shasum -a 256 "${OUTPUT_DIR}/rootfs.qcow2" | awk '{print $1}')"

cat > "${OUTPUT_DIR}/manifest.json" <<EOF
{
  "distro": "Alpine Linux",
  "version": "${ALPINE_VERSION}",
  "arch": "${ALPINE_ARCH}",
  "upstream_sources": {
    "minirootfs_url": "${MINIROOTFS_URL}",
    "minirootfs_sha256": "${MINIROOTFS_SHA256}",
    "netboot_url": "${NETBOOT_URL}",
    "netboot_sha256": "${NETBOOT_SHA256}",
    "builder_image": "${ALPINE_CONTAINER_IMAGE}"
  },
  "sha256": {
    "vmlinuz-virt": "${KERNEL_HASH}",
    "initramfs-virt": "${INITRD_HASH}",
    "rootfs.qcow2": "${ROOTFS_HASH}"
  }
}
EOF
chmod 0644 "${OUTPUT_DIR}/manifest.json"

echo "==> Guest image build complete in ${OUTPUT_DIR}"
