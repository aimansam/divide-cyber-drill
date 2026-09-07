#!/usr/bin/env python3
"""Upload + register a cloud-init-ready VM as a Proxmox template.

Usage (inside the API container or wherever proxmoxer is installed):
    python tools/upload_cloudinit_template.py \
        --name tpl-debian-cloudinit \
        --iso local:iso/debian-13.4.0-amd64-netinst.iso \
        --disk-storage local-lvm \
        --disk-gb 20 \
        --memory 2048 \
        --cores 2

What it does:
    1. Connects to PVE via proxmoxer (using PROXMOX_* env).
    2. Picks the first node (or --node).
    3. Allocates the next free VMID.
    4. Creates a VM with:
         - scsi0 on <disk-storage>, <disk-gb>G
         - ide2 on local:cloudinit (so cloud-init drive is wired in)
         - ide3 on <iso storage>:iso/<iso-name> (the install media)
         - boot=order=scsi0 (oride2)
         - agent=1, scsihw=virtio-scsi-single
    5. Sets template=1 on the VM.
    6. Prints the new VMID + name. Once it appears in
       `GET /api/v1/proxmox/templates`, the runner can clone it.

This script is intentionally idempotent per `--name`:
    - If a template with the given name already exists, it prints the
      existing VMID and exits 0.
    - Otherwise it creates a new one.

It does NOT actually run the installer — PVE has no unattended preseed
here, so the operator must boot the VM once in the GUI, run the
installer interactively, run `apt-get install qemu-guest-agent`, shut
down, and re-run this script with `--convert-only <vmid>` to flip
template=1 on the existing VM. We support both flows.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Repo root on path so this works from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from proxmoxer import ProxmoxAPI

from app.services.proxmox import ProxmoxNotConfiguredError, _validate_config


def _client() -> ProxmoxAPI:
    host, user, token_name, token_secret = _validate_config()
    return ProxmoxAPI(
        host=host,
        port=int(os.environ.get("PROXMOX_PORT", "8006")),
        user=user,
        token_name=token_name,
        token_value=token_secret,
        verify_ssl=os.environ.get("PROXMOX_VERIFY_SSL", "true").lower()
        in ("1", "true", "yes"),
        backend="https",
    )


def _parse_iso(volid: str) -> tuple[str, str]:
    """Split 'local:iso/debian-XX.iso' into (storage, 'iso/debian-XX.iso')."""
    storage, _, path = volid.partition(":")
    if not path:
        raise ValueError(f"bad iso volid: {volid!r}")
    return storage, path


def _find_existing_template(client: ProxmoxAPI, name: str) -> int | None:
    """Return VMID of template named `name`, or None."""
    try:
        resources = client.cluster.resources.get(type="vm")
    except Exception:  # noqa: BLE001
        resources = []
    for r in resources:
        if r.get("template") and r.get("name") == name:
            return int(r["vmid"])
    return None


def _pick_node(client: ProxmoxAPI) -> str:
    nodes = [n["node"] for n in client.nodes.get() if n.get("status") == "online"]
    if not nodes:
        raise RuntimeError("no online PVE nodes")
    return nodes[0]


def _allocate_vmid(client: ProxmoxAPI) -> int:
    return int(client.cluster.nextid.get())


def _verify_iso_present(client: ProxmoxAPI, node: str, iso: str) -> None:
    storage, path = _parse_iso(iso)
    items = client.nodes(node).storage(storage).content.get()
    if not any(i.get("volid") == iso for i in items):
        raise RuntimeError(
            f"ISO {iso!r} not found on {storage!r}. "
            f"Upload it first (PVE GUI: Datacenter → {node} → {storage} → ISO Images → Upload)."
        )


def _create_vm(
    client: ProxmoxAPI,
    *,
    node: str,
    vmid: int,
    name: str,
    iso: str,
    disk_storage: str,
    disk_gb: int,
    memory_mb: int,
    cores: int,
) -> None:
    iso_storage, iso_path = _parse_iso(iso)
    params = {
        "node": node,
        "vmid": vmid,
        "name": name,
        "memory": memory_mb,
        "cores": cores,
        "sockets": 1,
        "scsihw": "virtio-scsi-single",
        # scsi0: primary disk on the chosen storage.
        "scsi0": f"{disk_storage}:{disk_gb}",
        # ide2: cloud-init drive (CD-ROM bus, special handler).
        "ide2": "local:cloudinit",
        # ide3: install media (the ISO we pointed at).
        "ide3": f"{iso_storage}:{iso_path},media=cdrom",
        # Boot order: disk first, then ISO.
        "boot": "order=scsi0;ide3",
        # qemu guest agent so PVE can read IPs.
        "agent": 1,
    }
    try:
        client.nodes(node).qemu.post(**params)
    except Exception as exc:  # noqa: BLE001
        raise _wrap_403(exc, "create VM") from exc


def _set_template(client: ProxmoxAPI, *, node: str, vmid: int) -> None:
    try:
        client.nodes(node).qemu(vmid).config.post(template=1)
    except Exception as exc:  # noqa: BLE001
        raise _wrap_403(exc, "set template=1") from exc


_HINT = (
    "    The drill token needs PVEVMAdmin (or PVEAdmin) at path /v2/vm.\n"
    "    On the PVE host, run:\n"
    "      pveum acl modify /v2/vm --userid divide@pve@pam --role PVEVMAdmin\n"
    "    (or grant PVEAdmin at / for a broader token).\n"
    "    See README.md §8 §6 for the full procedure."
)


def _wrap_403(exc: Exception, op: str) -> Exception:
    msg = str(exc)
    if "403" in msg or "Permission check failed" in msg:
        return RuntimeError(
            f"PVE denied {op!r} (403 Forbidden).\n"
            f"{_HINT}\n"
            f"Original error: {exc}"
        )
    return exc


def _wait_for_task(
    client: ProxmoxAPI, node: str, upid: str, timeout_s: float = 120.0
) -> None:
    """Poll a PVE task by UPID until it completes. Best-effort."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            status = client.nodes(node).tasks(upid).status.get()
        except Exception:  # noqa: BLE001
            time.sleep(1)
            continue
        if status.get("status") == "stopped":
            if status.get("exitstatus") != "OK":
                raise RuntimeError(
                    f"task {upid} failed: {status.get('exitstatus')}"
                )
            return
        time.sleep(1)
    raise TimeoutError(f"task {upid} did not finish within {timeout_s}s")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--name", required=True, help="Template name (e.g. tpl-debian-cloudinit)")
    ap.add_argument("--iso", required=True, help="ISO volid, e.g. local:iso/debian-13-netinst.iso")
    ap.add_argument("--disk-storage", default="local-lvm", help="Storage for the VM disk")
    ap.add_argument("--disk-gb", type=int, default=20, help="Disk size in GB")
    ap.add_argument("--memory", type=int, default=2048, help="RAM in MB")
    ap.add_argument("--cores", type=int, default=2, help="vCPU cores")
    ap.add_argument("--node", default=None, help="PVE node (default: first online)")
    ap.add_argument(
        "--convert-only",
        type=int,
        default=None,
        metavar="VMID",
        help="Don't create a new VM; just set template=1 on an existing VMID.",
    )
    ap.add_argument(
        "--wait", type=float, default=120.0, help="Task timeout in seconds (default 120)"
    )
    args = ap.parse_args()

    try:
        client = _client()
    except ProxmoxNotConfiguredError as exc:
        print(f"FAIL: {exc}")
        return 2

    # Idempotency: if the template already exists, print + exit.
    existing = _find_existing_template(client, args.name)
    if existing is not None:
        print(f"OK: template '{args.name}' already exists (vmid={existing})")
        return 0

    node = args.node or _pick_node(client)

    if args.convert_only is not None:
        # Just flip the existing VM to a template.
        _set_template(client, node=node, vmid=args.convert_only)
        print(f"OK: converted vmid={args.convert_only} on node={node!r} to template")
        return 0

    # Fresh-create flow.
    _verify_iso_present(client, node, args.iso)
    vmid = _allocate_vmid(client)
    print(f"[1/3] allocated vmid={vmid} on node={node!r}")
    _create_vm(
        client,
        node=node,
        vmid=vmid,
        name=args.name,
        iso=args.iso,
        disk_storage=args.disk_storage,
        disk_gb=args.disk_gb,
        memory_mb=args.memory,
        cores=args.cores,
    )
    print(f"[2/3] created VM vmid={vmid} name={args.name!r}")
    _set_template(client, node=node, vmid=vmid)
    print(f"[3/3] marked vmid={vmid} as template")

    # Quick sanity: confirm /cluster/resources sees it.
    found = _find_existing_template(client, args.name)
    if found != vmid:
        print(
            f"WARN: cluster lookup didn't immediately see the template "
            f"(expected {vmid}, got {found}). Usually fine — PVE caches."
        )
    else:
        print(f"OK: {args.name!r} visible as vmid={vmid} template")
    return 0


if __name__ == "__main__":
    sys.exit(main())
