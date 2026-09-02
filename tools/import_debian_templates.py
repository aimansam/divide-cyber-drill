#!/usr/bin/env python3
"""Import Debian cloud images as Proxmox templates."""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, '/DATA/Storage/docker/divide-cyber-drill/services/api')

from proxmoxer import ProxmoxAPI
from app.services.proxmox import _validate_config


def get_client():
    host, user, token_name, token_secret = _validate_config()
    return ProxmoxAPI(
        host=host,
        port=int(os.environ.get('PROXMOX_PORT', '8006')),
        user=user,
        token_name=token_name,
        token_value=token_secret,
        verify_ssl=os.environ.get('PROXMOX_VERIFY_SSL', 'true').lower() in ('1', 'true', 'yes'),
        backend='https',
    )


def import_template(client, node, name, image_path, cpu, ram, disk):
    """Import a cloud image as a template."""
    # Check if template exists
    resources = client.cluster.resources.get(type='vm')
    for r in resources:
        if r.get('name') == name and r.get('template'):
            print(f"  ✅ {name} already exists")
            return
    
    print(f"  Creating {name}...")
    
    # Allocate VMID
    vmid = int(client.cluster.nextid.get())
    
    # Create VM
    client.nodes(node).qemu.post(
        vmid=vmid,
        name=name,
        memory=ram,
        cores=cpu,
        sockets=1,
        scsihw='virtio-scsi-single',
        agent=1,
        net0='virtio,bridge=vmbr0',
    )
    
    # Import disk
    print(f"    Importing disk (this may take a minute)...")
    client.nodes(node).qemu(vmid).config.post(
        scsi0=f'local-lvm:0,import-from={image_path}'
    )
    
    # Wait for import
    time.sleep(5)
    
    # Add cloud-init drive
    client.nodes(node).qemu(vmid).config.post(ide2='local:cloudinit')
    
    # Set boot order
    client.nodes(node).qemu(vmid).config.post(boot='order=scsi0')
    
    # Convert to template
    client.nodes(node).qemu(vmid).config.post(template=1)
    
    print(f"  ✅ {name} created (vmid={vmid})")


def main():
    client = get_client()
    
    # Get node
    nodes = [n['node'] for n in client.nodes.get() if n.get('status') == 'online']
    if not nodes:
        print("Error: No online PVE nodes found", file=sys.stderr)
        sys.exit(1)
    
    node = nodes[0]
    print(f"Using node: {node}")
    print()
    
    # Check if cloud image exists
    image_path = '/DATA/Storage/docker/divide-cyber-drill/tools/cloud-images/debian-cloud.qcow2'
    if not os.path.exists(image_path):
        print("Error: Cloud image not found. Run download_cloud_images.sh first.", file=sys.stderr)
        sys.exit(1)
    
    print("Importing Debian templates from cloud image...")
    print()
    
    # Import templates
    templates = [
        ('tpl-debian-router', 2, 2048, 20),
        ('tpl-debian-syslog', 2, 2048, 20),
    ]
    
    for name, cpu, ram, disk in templates:
        import_template(client, node, name, image_path, cpu, ram, disk)
    
    print()
    print("✅ Debian templates imported successfully!")


if __name__ == '__main__':
    main()
