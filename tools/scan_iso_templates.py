#!/usr/bin/env python3
"""Scan PVE for available ISOs and match them to required templates.

Usage:
    python tools/scan_iso_templates.py

Output:
    - Lists all ISOs on PVE
    - Shows which ISOs match which templates
    - Outputs a JSON mapping for use by setup_templates.sh
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from proxmoxer import ProxmoxAPI
from app.services.proxmox import _validate_config

# Pattern matching: template name patterns -> ISO name patterns
TEMPLATE_ISO_PATTERNS = {
    'tpl-debian-cloudinit': ['debian'],
    'tpl-debian-router': ['debian'],
    'tpl-debian-syslog': ['debian'],
    'tpl-kali-cloudinit': ['kali'],
    'tpl-win11-enterprise': ['windows', 'win11', 'win-11'],
    'tpl-win2022-dc': ['server', '2022', 'win-server'],
    'tpl-win2022-member': ['server', '2022', 'win-server'],
}

# Template specifications
TEMPLATE_SPECS = {
    'tpl-debian-cloudinit': {'cpu': 2, 'ram': 2048, 'disk': 20},
    'tpl-debian-router': {'cpu': 2, 'ram': 2048, 'disk': 20},
    'tpl-debian-syslog': {'cpu': 2, 'ram': 2048, 'disk': 20},
    'tpl-kali-cloudinit': {'cpu': 4, 'ram': 4096, 'disk': 40},
    'tpl-win11-enterprise': {'cpu': 4, 'ram': 4096, 'disk': 60},
    'tpl-win2022-dc': {'cpu': 4, 'ram': 4096, 'disk': 60},
    'tpl-win2022-member': {'cpu': 4, 'ram': 4096, 'disk': 60},
}


def get_client() -> ProxmoxAPI:
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


def get_isos(client: ProxmoxAPI, node: str) -> list[dict]:
    """Get all ISOs from local storage."""
    try:
        content = client.nodes(node).storage('local').content.get()
        return [c for c in content if c.get('content') == 'iso']
    except Exception as e:
        print(f"Warning: Could not list ISOs: {e}", file=sys.stderr)
        return []


def get_existing_templates(client: ProxmoxAPI) -> set[str]:
    """Get names of existing templates."""
    resources = client.cluster.resources.get(type='vm')
    return {r['name'] for r in resources if r.get('template')}


def match_iso_to_template(isos: list[dict], template_name: str) -> str | None:
    """Find the best ISO match for a template."""
    patterns = TEMPLATE_ISO_PATTERNS.get(template_name, [])
    
    for iso in isos:
        volid = iso.get('volid', '')
        name = volid.split('/')[-1].lower()
        
        for pattern in patterns:
            if pattern in name:
                return volid
    
    return None


def main():
    client = get_client()
    
    # Get first online node
    nodes = [n['node'] for n in client.nodes.get() if n.get('status') == 'online']
    if not nodes:
        print("Error: No online PVE nodes found", file=sys.stderr)
        sys.exit(1)
    
    node = nodes[0]
    print(f"Using node: {node}")
    print()
    
    # Get ISOs
    isos = get_isos(client, node)
    print(f"Found {len(isos)} ISOs:")
    for iso in sorted(isos, key=lambda x: x.get('volid', '')):
        volid = iso.get('volid', '')
        size_mb = iso.get('size', 0) / (1024 * 1024)
        print(f"  - {volid} ({size_mb:.1f} MB)")
    print()
    
    # Get existing templates
    existing = get_existing_templates(client)
    print(f"Existing templates: {sorted(existing)}")
    print()
    
    # Match ISOs to templates
    print("Template-ISO Mapping:")
    mapping = {}
    for template_name in sorted(TEMPLATE_SPECS.keys()):
        if template_name in existing:
            print(f"  ✅ {template_name}: already exists")
            continue
        
        iso = match_iso_to_template(isos, template_name)
        if iso:
            mapping[template_name] = iso
            spec = TEMPLATE_SPECS[template_name]
            print(f"  📀 {template_name}: {iso.split('/')[-1]} ({spec['cpu']} CPU, {spec['ram']}MB RAM, {spec['disk']}GB disk)")
        else:
            print(f"  ❌ {template_name}: no matching ISO found")
    
    print()
    
    # Output JSON mapping for setup script
    if mapping:
        output = {
            'node': node,
            'templates': {
                name: {
                    'iso': iso,
                    **TEMPLATE_SPECS[name]
                }
                for name, iso in mapping.items()
            }
        }
        print("JSON mapping (for setup script):")
        print(json.dumps(output, indent=2))
        
        # Save to file
        output_file = Path(__file__).parent / 'template_mapping.json'
        with open(output_file, 'w') as f:
            json.dump(output, f, indent=2)
        print(f"\nSaved to: {output_file}")
    else:
        print("No templates to create.")


if __name__ == '__main__':
    main()
