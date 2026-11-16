# AI Sandbox ARM64 Guest OS & Image Provenance

## 1. Distribution & Target Architecture
- **Guest OS**: Alpine Linux 3.21.3 (`aarch64`), `virt` kernel flavour.
- **Target platform**: `qemu-system-aarch64 -machine virt,usb=off -accel hvf -cpu host` on Apple Silicon macOS.
- **Execution user**: Unprivileged numeric user `10001:10001` (`sandbox:sandbox`).

## 2. Upstream Artifacts & Checksum Pins
All upstream artifacts used by `guest/scripts/build_guest_image.sh` are pinned and verified against official upstream release checksums (`.sha256`) from Alpine Linux:

| Artifact | Source | Verified SHA-256 Digest |
|---|---|---|
| `alpine-minirootfs-3.21.3-aarch64.tar.gz` | `https://dl-cdn.alpinelinux.org/alpine/v3.21/releases/aarch64/` | `ead8a4b37867bd19e7417dd078748e2312c0aea364403d96758d63ea8ff261ea` |
| `alpine-netboot-3.21.3-aarch64.tar.gz` | `https://dl-cdn.alpinelinux.org/alpine/v3.21/releases/aarch64/` | `601a090c2ca778798a54f4caed6b064a08904c97380d62bb6e507fa5a9a00c80` |
| Builder container `alpine:3.21` (`linux/arm64/v8`) | Docker Hub (`library/alpine:3.21`) | `alpine@sha256:e77b401c86e6d0651b12ca45dea812bdf6ffca3b6e16662b7c116180e56ec9f7` |

These pins are maintained in `guest/scripts/guest_image_pins.env`.

## 3. Generated Immutable Boot Assets (`.sandboxes/qemu/images/`)
- `vmlinuz-virt`: Official Alpine ARM64 `virt` kernel extracted from `alpine-netboot-3.21.3-aarch64.tar.gz`.
- `initramfs-virt`: Immutable `newc` cpio archive compressed with gzip, containing Python 3, `/init` (`guest/system/init`), and `/opt/aisandbox/guest_agent.py` (mode `0700`, owned by `0:0`).
- `rootfs.qcow2`: Empty immutable base qcow2 disk image used as the read-only backing file for disposable per-execution overlays.
- `manifest.json`: Cryptographic manifest recording the SHA-256 digests of `vmlinuz-virt`, `initramfs-virt`, and `rootfs.qcow2`. Verified by `QemuImageManager.verify_guest_assets()` prior to launching any VM.
