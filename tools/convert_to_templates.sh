#!/bin/bash
# Convert installed VMs to templates
# Run this after installing OS on each VM and shutting them down

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

log_step "Converting VMs to templates..."

python3 << 'PYEOF'
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from proxmoxer import ProxmoxAPI
from app.services.proxmox import _validate_config

# Load mapping
mapping_file = Path(__file__).parent / 'template_mapping.json'
with open(mapping_file) as f:
    mapping = json.load(f)

node = mapping['node']
templates = mapping['templates']

print(f"Node: {node}")
print(f"Templates to convert: {len(templates)}")
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
existing_vms = {r['name']: r for r in resources if not r.get('template')}
existing_templates = {r['name'] for r in resources if r.get('template')}

converted = []

for template_name in templates.keys():
    # Check if already a template
    if template_name in existing_templates:
        print(f"✅ {template_name}: already a template")
        continue
    
    # Check if VM exists
    if template_name not in existing_vms:
        print(f"❌ {template_name}: VM not found")
        continue
    
    vm = existing_vms[template_name]
    vmid = vm['vmid']
    status = vm.get('status', 'unknown')
    
    print(f"Converting {template_name} (vmid={vmid}, status={status})...")
    
    # Check if VM is stopped
    if status != 'stopped':
        print(f"⚠️  {template_name} is {status}, not stopped")
        print(f"   Please shutdown the VM first:")
        print(f"   pvesh create /nodes/{node}/qemu/{vmid}/status/shutdown")
        print()
        continue
    
    try:
        # Set template flag
        client.nodes(node).qemu(vmid).config.post(template=1)
        
        print(f"✅ {template_name} converted to template")
        print()
        
        converted.append(template_name)
        
    except Exception as e:
        print(f"❌ Failed to convert {template_name}: {e}")
        print()

print("=" * 60)
print(f"Converted {len(converted)} VMs to templates")
print("=" * 60)
print()

if converted:
    print("Verification:")
    resources = client.cluster.resources.get(type='vm')
    all_templates = {r['name']: r['vmid'] for r in resources if r.get('template')}
    
    print()
    print("All templates:")
    for name in sorted(all_templates.keys()):
        print(f"  ✅ {name} (vmid={all_templates[name]})")
    
    print()
    print("Required templates for scenarios:")
    required = [
        'tpl-debian-cloudinit',
        'tpl-kali-cloudinit',
        'tpl-win11-enterprise',
        'tpl-win2022-dc',
        'tpl-win2022-member',
        'tpl-debian-router',
        'tpl-debian-syslog',
    ]
    
    for name in required:
        if name in all_templates:
            print(f"  ✅ {name}")
        else:
            print(f"  ❌ {name} (missing)")
    
    print()
    print("Playability:")
    scenarios = {
        'first-live-drill': ['tpl-debian-cloudinit'],
        'red-vs-blue-baseline': ['tpl-kali-cloudinit', 'tpl-debian-router', 'tpl-debian-cloudinit', 'tpl-debian-syslog'],
        'lateral-movement-baseline': ['tpl-kali-cloudinit', 'tpl-win11-enterprise', 'tpl-win2022-dc'],
        'phish-to-ransom': ['tpl-kali-cloudinit', 'tpl-win11-enterprise', 'tpl-win2022-dc', 'tpl-win2022-member'],
    }
    
    for scenario, needed in scenarios.items():
        missing = [t for t in needed if t not in all_templates]
        if not missing:
            print(f"  ✅ {scenario}: playable")
        else:
            print(f"  ❌ {scenario}: missing {missing}")
else:
    print("No VMs converted. Check if VMs are shut down.")
PYEOF
