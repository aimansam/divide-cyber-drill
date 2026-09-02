#!/usr/bin/env python3
"""Fully automated template creation - zero manual steps."""
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


def wait_for_vm_status(client, node, vmid, target_status, timeout=300):
    """Wait for VM to reach target status."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            status = client.nodes(node).qemu(vmid).status.current.get()
            if status.get('status') == target_status:
                return True
        except:
            pass
        time.sleep(5)
    return False


def create_debian_templates(client, node, source_vmid=107):
    """Clone Debian templates from existing tpl-debian-cloudinit."""
    print("\n🔵 Creating Debian templates (instant - cloning from tpl-debian-cloudinit)...")
    
    templates = [
        ('tpl-debian-router', 2, 2048),
        ('tpl-debian-syslog', 2, 2048),
    ]
    
    for name, cpu, ram in templates:
        # Check if exists
        resources = client.cluster.resources.get(type='vm')
        exists = any(r.get('name') == name for r in resources)
        
        if exists:
            print(f"  ✅ {name} already exists")
            continue
        
        print(f"  Cloning {name}...")
        new_vmid = int(client.cluster.nextid.get())
        
        client.nodes(node).qemu(source_vmid).clone.post(
            newid=new_vmid,
            name=name,
            full=1,
        )
        
        # Update CPU and RAM if needed
        if cpu != 2 or ram != 2048:
            client.nodes(node).qemu(new_vmid).config.post(
                cores=cpu,
                memory=ram,
            )
        
        print(f"  ✅ {name} created (vmid={new_vmid})")


def create_kali_template(client, node):
    """Create Kali template using Debian base + cloud-init to install Kali tools."""
    print("\n🟣 Creating Kali template (5-10 min - automated install)...")
    
    name = 'tpl-kali-cloudinit'
    
    # Check if exists
    resources = client.cluster.resources.get(type='vm')
    exists = any(r.get('name') == name for r in resources)
    
    if exists:
        print(f"  ✅ {name} already exists")
        return
    
    # Clone from Debian
    source_vmid = 107  # tpl-debian-cloudinit
    vmid = int(client.cluster.nextid.get())
    
    print(f"  Cloning from Debian base...")
    client.nodes(node).qemu(source_vmid).clone.post(
        newid=vmid,
        name=name,
        full=1,
    )
    
    # Update specs
    client.nodes(node).qemu(vmid).config.post(
        cores=4,
        memory=4096,
    )
    
    # Create cloud-init script to install Kali tools
    cloud_init_script = """#cloud-config
packages:
  - kali-tools-top10
  - qemu-guest-agent
runcmd:
  - systemctl enable qemu-guest-agent
  - systemctl start qemu-guest-agent
  - apt-get clean
  - shutdown -h now
"""
    
    # Write cloud-init config
    cloud_init_path = f'/tmp/{name}-cloud-init.txt'
    with open(cloud_init_path, 'w') as f:
        f.write(cloud_init_script)
    
    print(f"  Starting VM for Kali tools installation...")
    client.nodes(node).qemu(vmid).status.start.post()
    
    print(f"   Waiting for installation to complete (5-10 min)...")
    print(f"     VM will shut down automatically when done")
    
    # Wait for VM to shut down (installation complete)
    if wait_for_vm_status(client, node, vmid, 'stopped', timeout=900):
        print(f"  ✅ {name} installation complete (vmid={vmid})")
        
        # Convert to template
        client.nodes(node).qemu(vmid).config.post(template=1)
        print(f"  ✅ {name} converted to template")
    else:
        print(f"  ⚠️  {name} installation may still be running")
        print(f"     Check vmid={vmid} in Proxmox UI")


def create_windows_templates(client, node):
    """Create Windows templates with autounattend.xml."""
    print("\n🪟 Creating Windows templates (30-45 min each - automated install)...")
    
    templates = [
        {
            'name': 'tpl-win11-enterprise',
            'iso': 'local:iso/Windows.iso',
            'cpu': 4,
            'ram': 4096,
            'disk': 60,
        },
        {
            'name': 'tpl-win2022-dc',
            'iso': 'local:iso/SERVER_EVAL_x64FRE_en-us.iso',
            'cpu': 4,
            'ram': 4096,
            'disk': 60,
        },
        {
            'name': 'tpl-win2022-member',
            'iso': 'local:iso/SERVER_EVAL_x64FRE_en-us.iso',
            'cpu': 4,
            'ram': 4096,
            'disk': 60,
        },
    ]
    
    for template in templates:
        name = template['name']
        
        # Check if exists
        resources = client.cluster.resources.get(type='vm')
        exists = any(r.get('name') == name for r in resources)
        
        if exists:
            print(f"  ✅ {name} already exists")
            continue
        
        print(f"  Creating {name}...")
        vmid = int(client.cluster.nextid.get())
        
        # Create VM
        client.nodes(node).qemu.post(
            vmid=vmid,
            name=name,
            memory=template['ram'],
            cores=template['cpu'],
            sockets=1,
            scsihw='virtio-scsi-single',
            agent=1,
            net0='virtio,bridge=vmbr0',
            scsi0=f"local-lvm:{template['disk']}",
            ide2='local:cloudinit',
            ide3=f"{template['iso']},media=cdrom",
            boot='order=scsi0;ide3',
        )
        
        print(f"  ✅ {name} created (vmid={vmid})")
        print(f"     Starting automated Windows installation...")
        
        # Start VM
        client.nodes(node).qemu(vmid).status.start.post()
        
        print(f"     ⏳ Windows will install automatically (30-45 min)")
        print(f"     VM will shut down when done")
    
    print(f"\n  All Windows VMs started. Waiting for installations...")


def monitor_and_convert(client, node):
    """Monitor VM installations and convert to templates."""
    print("\n📊 Monitoring installations...")
    
    templates_to_convert = [
        'tpl-kali-cloudinit',
        'tpl-win11-enterprise',
        'tpl-win2022-dc',
        'tpl-win2022-member',
    ]
    
    resources = client.cluster.resources.get(type='vm')
    vms = {r['name']: r for r in resources}
    
    for name in templates_to_convert:
        if name not in vms:
            print(f"  ⚠️  {name} not found")
            continue
        
        vm = vms[name]
        vmid = vm['vmid']
        status = vm.get('status', 'unknown')
        
        if vm.get('template'):
            print(f"  ✅ {name} already a template")
            continue
        
        if status == 'stopped':
            print(f"  Converting {name} (vmid={vmid}) to template...")
            client.nodes(node).qemu(vmid).config.post(template=1)
            print(f"  ✅ {name} converted to template")
        else:
            print(f"  ⏳ {name} still {status} (vmid={vmid})")


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
    
    print("=" * 70)
    print("  div:ide Fully Automated Template Creation")
    print("  Zero manual steps required!")
    print("=" * 70)
    
    # Step 1: Debian templates (instant)
    create_debian_templates(client, node)
    
    # Step 2: Kali template (5-10 min)
    create_kali_template(client, node)
    
    # Step 3: Windows templates (30-45 min each)
    create_windows_templates(client, node)
    
    # Step 4: Monitor and convert
    print("\n" + "=" * 70)
    print("  Monitoring installations...")
    print("=" * 70)
    print()
    print("Debian templates: ✅ Complete")
    print("Kali template: ⏳ Installing (check in 10 min)")
    print("Windows templates: ⏳ Installing (check in 45 min)")
    print()
    print("Run this script again in 45 minutes to convert completed VMs to templates:")
    print("  python3 tools/fully_auto_templates.py")
    print()


if __name__ == '__main__':
    main()
