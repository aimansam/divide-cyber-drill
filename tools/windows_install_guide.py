#!/usr/bin/env python3
"""Windows Template Installation Guide and Monitor"""
import os
import sys
import time
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
        timeout=60,
    )


def check_vm_status(client, node, vmid):
    """Check if VM is running or stopped."""
    try:
        status = client.nodes(node).qemu(vmid).status.current.get()
        return status.get('status', 'unknown')
    except:
        return 'unknown'


def main():
    client = get_client()
    
    nodes = [n['node'] for n in client.nodes.get() if n.get('status') == 'online']
    if not nodes:
        print("Error: No online PVE nodes found", file=sys.stderr)
        sys.exit(1)
    
    node = nodes[0]
    
    print("=" * 70)
    print("  Windows Template Installation Guide")
    print("=" * 70)
    print()
    
    windows_vms = [
        {'name': 'tpl-win11-enterprise', 'vmid': 110, 'iso': 'Windows.iso'},
        {'name': 'tpl-win2022-dc', 'vmid': 111, 'iso': 'SERVER_EVAL_x64FRE_en-us.iso'},
        {'name': 'tpl-win2022-member', 'vmid': 112, 'iso': 'SERVER_EVAL_x64FRE_en-us.iso'},
    ]
    
    print("Windows VMs created and ready for installation:")
    print()
    
    for vm in windows_vms:
        status = check_vm_status(client, node, vm['vmid'])
        print(f"  {vm['name']} (vmid={vm['vmid']}) - Status: {status}")
    
    print()
    print("=" * 70)
    print("  Installation Instructions (per VM)")
    print("=" * 70)
    print()
    print("For each Windows VM above:")
    print()
    print("1. Open Proxmox web UI: https://192.168.0.10:8006")
    print("2. Click on the VM (e.g., tpl-win11-enterprise)")
    print("3. Click 'Start' button")
    print("4. Click 'Console' to open VM console")
    print("5. Windows installer will boot automatically")
    print()
    print("6. During installation:")
    print("   - Language: English")
    print("   - Click 'Install now'")
    print("   - Skip product key (evaluation mode)")
    print("   - Select Windows edition (Enterprise or Server)")
    print("   - Accept license terms")
    print("   - Select 'Custom: Install Windows only (advanced)'")
    print("   - Select disk and click 'Next'")
    print()
    print("7. After installation completes:")
    print("   - Login as Administrator")
    print("   - Password: Divide123!")
    print()
    print("8. Install VirtIO drivers:")
    print("   - In Proxmox, attach virtio-win-0.1.285.iso as CD-ROM")
    print("   - In Windows, open Device Manager")
    print("   - Update drivers for unknown devices")
    print("   - Browse to VirtIO CD-ROM and install all drivers")
    print()
    print("9. Install qemu-guest-agent:")
    print("   - Open VirtIO CD-ROM")
    print("   - Run: guest-agent/qemu-ga-x86_64.msi")
    print("   - Accept defaults and install")
    print()
    print("10. Shutdown VM:")
    print("    - Start menu → Power → Shutdown")
    print()
    print("=" * 70)
    print("  After All VMs Are Shut Down")
    print("=" * 70)
    print()
    print("Run this command to convert VMs to templates:")
    print()
    print("  cd /DATA/Storage/docker/divide-cyber-drill")
    print("  export PROXMOX_HOST=https://192.168.0.10 PROXMOX_PORT=8006")
    print("  export PROXMOX_USER=divide@pve@pam PROXMOX_TOKEN_ID=drill-token")
    print("  export PROXMOX_TOKEN_SECRET=4ea3414f-d3a4-47b5-a2ed-19018f416cc0")
    print("  export PROXMOX_VERIFY_SSL=false")
    print("  export PYTHONPATH=/DATA/Storage/docker/divide-cyber-drill/services/api")
    print("  python3 tools/convert_to_templates.py")
    print()
    print("=" * 70)
    print("  Estimated Time")
    print("=" * 70)
    print()
    print("  - Windows installation: 30-45 minutes per VM")
    print("  - VirtIO + qemu-guest-agent: 5 minutes per VM")
    print("  - Total: ~2 hours for all 3 VMs")
    print()
    print("=" * 70)


if __name__ == '__main__':
    main()
