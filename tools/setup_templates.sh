#!/bin/bash
# Create VMs for templates based on template_mapping.json
# After running this, manually install OS on each VM, then run convert_to_templates.sh

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step() { echo -e "${BLUE}[STEP]${NC} $1"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAPPING_FILE="$SCRIPT_DIR/template_mapping.json"

if [ ! -f "$MAPPING_FILE" ]; then
    log_error "template_mapping.json not found"
    log_info "Run: python tools/scan_iso_templates.py first"
    exit 1
fi

log_step "Reading template mapping..."

# Parse JSON and create VMs
python3 << 'PYEOF'
import json
import os
import sys
from pathlib import Path

# Add services/api to path
sys.path.insert(0, '/DATA/Storage/docker/divide-cyber-drill/services/api')

from proxmoxer import ProxmoxAPI
from app.services.proxmox import _validate_config

# Load mapping
mapping_file = Path('/DATA/Storage/docker/divide-cyber-drill/tools/template_mapping.json')
with open(mapping_file) as f:
    mapping = json.load(f)

node = mapping['node']
templates = mapping['templates']

print(f"Node: {node}")
print(f"Templates to create: {len(templates)}")
print()

# Get client
host, user, token_name, token_secret = _validate_config()
client = ProxmoxAPI(
    host=host,
    port=int(os.environ.get('PROXMOX_PORT', '8006')),
    user=user,
    token_name=token_name,
    token_value=token_secret,
    verify_ssl=os.environ.get('PROXMOX_VERIFY_SSL', 'true').lower() in ('1', 'true', 'yes'),
    backend='https',
)

# Get existing VMs and templates
resources = client.cluster.resources.get(type='vm')
existing_vms = {r['name']: r['vmid'] for r in resources}
existing_templates = {r['name'] for r in resources if r.get('template')}

created = []

for template_name, config in templates.items():
    iso = config['iso']
    cpu = config['cpu']
    ram = config['ram']
    disk = config['disk']
    
    # Check if already exists
    if template_name in existing_templates:
        print(f"✅ {template_name}: already exists as template")
        continue
    
    if template_name in existing_vms:
        print(f"️  {template_name}: already exists as VM (vmid={existing_vms[template_name]})")
        print(f"   Delete it first if you want to recreate")
        continue
    
    print(f"Creating {template_name}...")
    
    try:
        # Allocate VMID
        vmid = int(client.cluster.nextid.get())
        
        # Create VM
        client.nodes(node).qemu.post(
            vmid=vmid,
            name=template_name,
            memory=ram,
            cores=cpu,
            sockets=1,
            scsihw='virtio-scsi-single',
            agent=1,
            net0='virtio,bridge=vmbr0',
            scsi0=f"local-lvm:{disk}",
            ide2='local:cloudinit',
            ide3=f"{iso},media=cdrom",
            boot='order=scsi0;ide3',
        )
        
        print(f"✅ {template_name} created (vmid={vmid})")
        print(f"   CPU: {cpu}, RAM: {ram}MB, Disk: {disk}GB")
        print(f"   ISO: {iso.split('/')[-1]}")
        print()
        
        created.append({'name': template_name, 'vmid': vmid})
        
    except Exception as e:
        print(f"❌ Failed to create {template_name}: {e}")
        print()

print("=" * 60)
print(f"Created {len(created)} VMs")
print("=" * 60)
print()

if created:
    print("Next steps:")
    print()
    print("1. Open Proxmox web UI")
    print("2. For each VM:")
    print("   a. Click on the VM")
    print("   b. Click 'Start'")
    print("   c. Click 'Console' to open the console")
    print("   d. Run through the OS installer")
    print("   e. After installation, login and run:")
    print()
    print("      # For Debian/Kali:")
    print("      apt-get update && apt-get install -y qemu-guest-agent")
    print("      systemctl enable --now qemu-guest-agent")
    print("      shutdown -h now")
    print()
    print("      # For Windows:")
    print("      - Install VirtIO drivers from virtio-win-0.1.285.iso")
    print("      - Install qemu-guest-agent")
    print("      - Shutdown")
    print()
    print("3. After all VMs are shut down, run:")
    print("   ./tools/convert_to_templates.sh")
    print()
else:
    print("No VMs created. All templates may already exist.")
PYEOF
