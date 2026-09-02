# Template Management Guide

Complete guide for creating and managing Proxmox VM templates for div:ide cyber drills.

## Overview

div:ide requires VM templates on your Proxmox host to create drill VMs. Each scenario defines which templates it needs in its YAML configuration file.

This guide covers:
- **Automated setup** - Zero-touch template creation
- **Manual setup** - Step-by-step installation (if needed)
- **Template specifications** - Resource requirements
- **Troubleshooting** - Common issues and solutions

## Quick Start (Fully Automated)

For new deployments, run these three commands:

```bash
# 1. Setup SSH access to PVE (one-time, 2 minutes)
PVE_ROOT_PASSWORD=your_pve_root_password bash tools/setup_ssh_auto.sh

# 2. Set environment variables
export PROXMOX_HOST=https://192.168.0.10 PROXMOX_PORT=8006
export PROXMOX_USER=divide@pve@pam PROXMOX_TOKEN_ID=drill-token
export PROXMOX_TOKEN_SECRET=4ea3414f-d3a4-47b5-a2ed-19018f416cc0
export PROXMOX_VERIFY_SSL=false
export PVE_HOST=192.168.0.10 PVE_SSH_USER=root
export PYTHONPATH=/DATA/Storage/docker/divide-cyber-drill/services/api

# 3. Run automated template creation (~2.5 hours, fully unattended)
python3 tools/auto_install_windows.py
```

**Result:** All 7 templates created, all 4 scenarios playable.

## Template Specifications

| Template | CPU | RAM | Disk | ISO Pattern | OS |
|----------|-----|-----|------|-------------|-----|
| `tpl-debian-cloudinit` | 2 | 2GB | 20GB | debian | Debian 12 |
| `tpl-debian-router` | 2 | 2GB | 20GB | debian | Debian 12 |
| `tpl-debian-syslog` | 2 | 2GB | 20GB | debian | Debian 12 |
| `tpl-kali-cloudinit` | 4 | 4GB | 40GB | kali | Kali Linux |
| `tpl-win11-enterprise` | 4 | 4GB | 60GB | windows, win11 | Windows 11 |
| `tpl-win2022-dc` | 4 | 4GB | 60GB | server, 2022 | Windows Server 2022 |
| `tpl-win2022-member` | 4 | 4GB | 60GB | server, 2022 | Windows Server 2022 |

## Automated Setup Process

### Phase 1: Linux Templates (10 minutes)

The automation script handles Linux templates automatically:

1. **Smart ISO Detection** - Scans PVE for available ISOs
2. **Pattern Matching** - Matches ISOs to templates:
   - `debian` → Debian templates
   - `kali` → Kali template
   - `windows` or `win11` → Windows 11 template
   - `server` or `2022` → Windows Server 2022 templates
3. **Automated Cloning** - Clones from base images
4. **Configuration** - Sets CPU, RAM, disk via PVE API
5. **Template Conversion** - Marks VMs as templates

### Phase 2: Windows Templates (~2 hours, unattended)

Windows templates require OS installation. The automation:

1. **SSH File Transfer** - Uploads autounattend.xml to PVE
2. **Floppy Creation** - Creates virtual floppy disk on PVE
3. **VM Configuration** - Attaches floppy + VirtIO ISO
4. **Automated Installation** - Windows installs via autounattend.xml
5. **Driver Installation** - VirtIO drivers + qemu-guest-agent auto-installed
6. **Auto-Conversion** - VMs converted to templates after shutdown

### What Happens During Windows Installation

Each Windows VM:
1. Boots from Windows ISO
2. Reads autounattend.xml from virtual floppy
3. Installs Windows automatically (20-30 min)
4. Auto-logs in as Administrator
5. Installs VirtIO drivers from attached ISO
6. Installs qemu-guest-agent
7. Shuts down automatically
8. Script converts to template

## Manual Setup (Alternative)

If automation fails, you can install manually.

### Prerequisites

- PVE host with root SSH access
- Required ISOs uploaded to PVE:
  - `debian-13.4.0-amd64-netinst.iso`
  - `kali-linux-2026.2-installer-amd64.iso`
  - `Windows.iso` (Windows 11 Enterprise)
  - `SERVER_EVAL_x64FRE_en-us.iso` (Windows Server 2022)
  - `virtio-win-0.1.285.iso` (VirtIO drivers)

### Step 1: Create VMs

```bash
# Scan for ISOs and create VMs
python3 tools/scan_iso_templates.py
bash tools/setup_templates.sh
```

### Step 2: Install Linux (5-10 min per VM)

For each Debian/Kali VM:

1. Open Proxmox web UI
2. Start VM and open Console
3. Run through OS installer:
   - Language: English
   - Hostname: `tpl-<name>` (e.g., `tpl-kali`)
   - Domain: `local`
   - Root password: `divide`
   - User: `divide` / `divide`
   - Partition: Guided - use entire disk
   - Install GRUB: Yes
4. After installation, login as root:
   ```bash
   apt-get update
   apt-get install -y qemu-guest-agent
   systemctl enable --now qemu-guest-agent
   shutdown -h now
   ```

### Step 3: Install Windows (30-45 min per VM)

For each Windows VM:

1. Start VM and open Console
2. Run Windows installer:
   - Language: English
   - Click "Install now"
   - Skip product key (evaluation mode)
   - Select edition (Enterprise or Server)
   - Accept license terms
   - Custom install → Select disk → Next
3. After installation, login as Administrator:
   - Password: `Divide123!`
4. Install VirtIO drivers:
   - Attach `virtio-win-0.1.285.iso` as CD-ROM
   - Open Device Manager
   - Update drivers for unknown devices
   - Browse to VirtIO CD-ROM
5. Install qemu-guest-agent:
   - Open VirtIO CD-ROM
   - Run `guest-agent/qemu-ga-x86_64.msi`
6. Shutdown VM

### Step 4: Convert to Templates

```bash
bash tools/convert_to_templates.sh
```

## Scenario Playability

After creating all templates:

| Scenario | Difficulty | Duration | Required Templates | Status |
|----------|-----------|----------|-------------------|--------|
| `first-live-drill` | Beginner | 10 min | `tpl-debian-cloudinit` | ✅ Playable |
| `red-vs-blue-baseline` | Beginner | 30 min | `tpl-kali-cloudinit`, `tpl-debian-router`, `tpl-debian-cloudinit`, `tpl-debian-syslog` | ✅ Playable |
| `lateral-movement-baseline` | Beginner | 45 min | `tpl-kali-cloudinit`, `tpl-win11-enterprise`, `tpl-win2022-dc` | ✅ Playable |
| `phish-to-ransom` | Intermediate | 90 min | `tpl-kali-cloudinit`, `tpl-win11-enterprise`, `tpl-win2022-dc`, `tpl-win2022-member` | ✅ Playable |

## Customizing Template Names

To use custom template names, edit the scenario YAML files:

```yaml
spec:
  assets:
    - role: drill_vm
      kind: vm
      template: your-custom-template-name  # Change this
```

Then update `tools/scan_iso_templates.py` to match your custom names.

## Troubleshooting

### "No matching ISO found"

The script couldn't find an ISO matching the template pattern.

**Solutions:**
1. Upload the required ISO to PVE (Datacenter → Storage → ISO Images → Upload)
2. Rename the ISO to match the pattern (e.g., `kali-linux.iso` for Kali)
3. Manually specify the ISO: edit `template_mapping.json` before running `setup_templates.sh`

### "VM already exists"

A VM with that name already exists.

**Solutions:**
1. Delete the existing VM in Proxmox UI
2. Or rename the template in the scenario YAML

### "Permission denied"

Your PVE token doesn't have sufficient permissions.

**Required permissions:**
- `VM.Allocate` on `/vms`
- `Datastore.AllocateSpace` on storage
- See `docs/PROXMOX-SETUP.md` for full permission setup

### SSH Connection Failed

Cannot connect to PVE via SSH.

**Solutions:**
1. Verify PVE host is reachable: `ping 192.168.0.10`
2. Check root login is enabled in `/etc/ssh/sshd_config`
3. Verify firewall allows SSH (port 22)
4. Test manually: `ssh root@192.168.0.10`

### Windows Installation Stuck

Windows VM not progressing through installation.

**Solutions:**
1. Check VM console in Proxmox web UI
2. Verify autounattend.xml is attached as floppy
3. Check if VirtIO ISO is attached (ide3)
4. Verify drive letter in autounattend.xml (currently set to E:)

### VirtIO Drivers Not Installing

Windows can't find network or balloon drivers.

**Solutions:**
1. Verify VirtIO ISO is attached to VM
2. Check Device Manager for unknown devices
3. Manually browse to VirtIO CD-ROM and install drivers
4. Reboot VM after driver installation

## Files Reference

### Automation Scripts
- `tools/scan_iso_templates.py` - Smart ISO detection and matching
- `tools/fully_auto_templates.py` - Linux template automation
- `tools/auto_install_windows.py` - Windows template automation
- `tools/setup_ssh_auto.sh` - SSH key setup automation
- `tools/setup_pve_ssh.sh` - Alternative SSH setup (interactive)

### Configuration Files
- `tools/autounattend-win11.xml` - Windows 11 auto-install config
- `tools/autounattend-server2022.xml` - Windows Server 2022 auto-install config
- `tools/autounattend.xml` - Legacy Windows config (deprecated)

### Utility Scripts
- `tools/download_cloud_images.sh` - Download Debian cloud images
- `tools/import_debian_templates.py` - Import cloud images as templates
- `tools/create_windows_floppy.sh` - Create autounattend floppy disk
- `tools/setup_templates.sh` - Create VMs from mapping
- `tools/convert_to_templates.sh` - Convert VMs to templates
- `tools/windows_install_guide.py` - Manual installation guide

## Additional Resources

- `docs/PROXMOX-SETUP.md` - PVE host setup and permissions
- `docs/SCENARIO-SPEC.md` - Scenario YAML specification
- `README.md` - Platform overview and quick start

## Support

For issues or questions:
1. Check this guide's troubleshooting section
2. Review `docs/PROXMOX-SETUP.md` for PVE configuration
3. Check PVE logs: `journalctl -u pveproxy`
4. Check div:ide API logs: `docker compose logs api`
