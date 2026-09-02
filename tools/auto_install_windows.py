#!/usr/bin/env python3
"""Fully automated Windows installation using SSH for file transfers."""
import os
import sys
import time
import subprocess
from pathlib import Path

sys.path.insert(0, '/DATA/Storage/docker/divide-cyber-drill/services/api')

from proxmoxer import ProxmoxAPI
from app.services.proxmox import _validate_config


# VM configurations
WINDOWS_VMS = [
    {
        'name': 'tpl-win11-enterprise',
        'vmid': 110,
        'iso': 'local:iso/Windows.iso',
        'cpu': 4,
        'ram': 4096,
        'disk': 60,
        'autounattend': 'autounattend-win11.xml',
    },
    {
        'name': 'tpl-win2022-dc',
        'vmid': 111,
        'iso': 'local:iso/SERVER_EVAL_x64FRE_en-us.iso',
        'cpu': 4,
        'ram': 4096,
        'disk': 60,
        'autounattend': 'autounattend-server2022.xml',
    },
    {
        'name': 'tpl-win2022-member',
        'vmid': 112,
        'iso': 'local:iso/SERVER_EVAL_x64FRE_en-us.iso',
        'cpu': 4,
        'ram': 4096,
        'disk': 60,
        'autounattend': 'autounattend-server2022.xml',
    },
]


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


def ssh_command(cmd, timeout=30):
    """Execute command on PVE host via SSH."""
    pve_host = os.environ.get('PVE_HOST', '192.168.0.10')
    pve_user = os.environ.get('PVE_SSH_USER', 'root')
    
    full_cmd = f"ssh -o StrictHostKeyChecking=no -o BatchMode=yes {pve_user}@{pve_host} '{cmd}'"
    
    try:
        result = subprocess.run(
            full_cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, '', 'Command timed out'
    except Exception as e:
        return False, '', str(e)


def scp_file(local_path, remote_path):
    """Copy file to PVE host via SCP."""
    pve_host = os.environ.get('PVE_HOST', '192.168.0.10')
    pve_user = os.environ.get('PVE_SSH_USER', 'root')
    
    cmd = f"scp -o StrictHostKeyChecking=no {local_path} {pve_user}@{pve_host}:{remote_path}"
    
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        return result.returncode == 0
    except:
        return False


def create_autounattend_files():
    """Create autounattend.xml files for Windows 11 and Server 2022."""
    tools_dir = Path('/DATA/Storage/docker/divide-cyber-drill/tools')
    
    # Windows 11 autounattend
    win11_xml = '''<?xml version="1.0" encoding="utf-8"?>
<unattend xmlns="urn:schemas-microsoft-com:unattend">
    <settings pass="windowsPE">
        <component name="Microsoft-Windows-International-Core-WinPE" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
            <SetupUILanguage><UILanguage>en-US</UILanguage></SetupUILanguage>
            <InputLocale>en-US</InputLocale>
            <SystemLocale>en-US</SystemLocale>
            <UILanguage>en-US</UILanguage>
            <UserLocale>en-US</UserLocale>
        </component>
        <component name="Microsoft-Windows-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
            <DiskConfiguration>
                <Disk wcm:action="add">
                    <DiskID>0</DiskID>
                    <WillWipeDisk>true</WillWipeDisk>
                    <CreatePartitions>
                        <CreatePartition wcm:action="add"><Order>1</Order><Type>Primary</Type><Size>100</Size></CreatePartition>
                        <CreatePartition wcm:action="add"><Order>2</Order><Type>Primary</Type><Extend>true</Extend></CreatePartition>
                    </CreatePartitions>
                    <ModifyPartitions>
                        <ModifyPartition wcm:action="add"><Order>1</Order><PartitionID>1</PartitionID><Format>NTFS</Format><Label>System</Label><Active>true</Active></ModifyPartition>
                        <ModifyPartition wcm:action="add"><Order>2</Order><PartitionID>2</PartitionID><Format>NTFS</Format><Label>Windows</Label><Letter>C</Letter></ModifyPartition>
                    </ModifyPartitions>
                </Disk>
            </DiskConfiguration>
            <ImageInstall>
                <OSImage>
                    <InstallFrom>
                        <MetaData wcm:action="add">
                            <Key>/IMAGE/NAME</Key>
                            <Value>Windows 11 Enterprise Evaluation</Value>
                        </MetaData>
                    </InstallFrom>
                    <InstallTo><DiskID>0</DiskID><PartitionID>2</PartitionID></InstallTo>
                </OSImage>
            </ImageInstall>
            <UserData>
                <AcceptEula>true</AcceptEula>
                <FullName>Divide</FullName>
                <Organization>Divide Cyber Drill</Organization>
            </UserData>
        </component>
    </settings>
    <settings pass="specialize">
        <component name="Microsoft-Windows-Shell-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
            <ComputerName>TEMPLATE</ComputerName>
        </component>
    </settings>
    <settings pass="oobeSystem">
        <component name="Microsoft-Windows-Shell-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
            <UserAccounts>
                <AdministratorPassword>
                    <Value>Divide123!</Value>
                    <PlainText>true</PlainText>
                </AdministratorPassword>
            </UserAccounts>
            <AutoLogon>
                <Password><Value>Divide123!</Value><PlainText>true</PlainText></Password>
                <Enabled>true</Enabled>
                <LogonCount>1</LogonCount>
                <Username>Administrator</Username>
            </AutoLogon>
            <FirstLogonCommands>
                <SynchronousCommand wcm:action="add">
                    <Order>1</Order>
                    <CommandLine>powershell -Command "Start-Process msiexec.exe -ArgumentList '/i E:\\guest-agent\\qemu-ga-x86_64.msi /quiet /norestart' -Wait"</CommandLine>
                </SynchronousCommand>
                <SynchronousCommand wcm:action="add">
                    <Order>2</Order>
                    <CommandLine>powershell -Command "Set-Service QEMU-GA -StartupType Automatic; Start-Service QEMU-GA"</CommandLine>
                </SynchronousCommand>
                <SynchronousCommand wcm:action="add">
                    <Order>3</Order>
                    <CommandLine>shutdown /s /t 10 /f</CommandLine>
                </SynchronousCommand>
            </FirstLogonCommands>
            <OOBE>
                <HideEULAPage>true</HideEULAPage>
                <HideLocalAccountScreen>true</HideLocalAccountScreen>
                <HideOEMRegistrationScreen>true</HideOEMRegistrationScreen>
                <HideOnlineAccountScreens>true</HideOnlineAccountScreens>
                <HideWirelessSetupInOOBE>true</HideWirelessSetupInOOBE>
                <NetworkLocation>Work</NetworkLocation>
                <ProtectYourPC>1</ProtectYourPC>
            </OOBE>
        </component>
    </settings>
</unattend>'''
    
    # Windows Server 2022 autounattend (same structure, different image name)
    server_xml = win11_xml.replace('Windows 11 Enterprise Evaluation', 'Windows Server 2022 SERVERSTANDARD')
    
    # Write files
    with open(tools_dir / 'autounattend-win11.xml', 'w') as f:
        f.write(win11_xml)
    
    with open(tools_dir / 'autounattend-server2022.xml', 'w') as f:
        f.write(server_xml)
    
    print("✅ Created autounattend.xml files")


def create_floppy_on_pve(vm_config):
    """Create floppy disk with autounattend.xml on PVE host."""
    vmid = vm_config['vmid']
    autounattend_file = vm_config['autounattend']
    
    print(f"  Creating floppy disk for {vm_config['name']}...")
    
    # Copy autounattend.xml to PVE
    local_path = f"/DATA/Storage/docker/divide-cyber-drill/tools/{autounattend_file}"
    remote_path = f"/tmp/{autounattend_file}"
    
    if not scp_file(local_path, remote_path):
        print(f"    ❌ Failed to upload {autounattend_file}")
        return False
    
    # Create floppy disk on PVE
    commands = [
        f"dd if=/dev/zero of=/tmp/autounattend-{vmid}.vfd bs=1024 count=1440 2>/dev/null",
        f"mkfs.vfat -F 12 /tmp/autounattend-{vmid}.vfd 2>/dev/null",
        f"mcopy -i /tmp/autounattend-{vmid}.vfd /tmp/{autounattend_file} ::/autounattend.xml",
        f"mkdir -p /var/lib/vz/images/{vmid}",
        f"cp /tmp/autounattend-{vmid}.vfd /var/lib/vz/images/{vmid}/vm-{vmid}-disk-1.vfd",
    ]
    
    for cmd in commands:
        success, stdout, stderr = ssh_command(cmd)
        if not success:
            print(f"    ❌ Command failed: {cmd}")
            print(f"       Error: {stderr}")
            return False
    
    print(f"    ✅ Floppy created on PVE")
    return True


def attach_floppy_to_vm(client, node, vm_config):
    """Attach floppy disk to VM."""
    vmid = vm_config['vmid']
    
    print(f"  Attaching floppy to {vm_config['name']}...")
    
    try:
        client.nodes(node).qemu(vmid).config.post(
            floppy0=f'local:{vmid}/vm-{vmid}-disk-1.vfd'
        )
        print(f"    ✅ Floppy attached")
        return True
    except Exception as e:
        print(f"    ❌ Failed to attach floppy: {e}")
        return False


def start_vm(client, node, vmid):
    """Start VM."""
    try:
        client.nodes(node).qemu(vmid).status.start.post()
        return True
    except Exception as e:
        print(f"    ❌ Failed to start VM: {e}")
        return False


def wait_for_vm_shutdown(client, node, vmid, timeout=3600):
    """Wait for VM to shut down (installation complete)."""
    print(f"  Waiting for installation to complete (timeout: {timeout//60} min)...")
    
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            status = client.nodes(node).qemu(vmid).status.current.get()
            if status.get('status') == 'stopped':
                return True
            
            # Show progress every 5 minutes
            elapsed = int(time.time() - start_time)
            if elapsed % 300 == 0 and elapsed > 0:
                print(f"    ⏳ Still installing... ({elapsed//60} min elapsed)")
        except:
            pass
        
        time.sleep(30)
    
    return False


def main():
    print("════════════════════════════════════════════════════════════════╗")
    print("║  Automated Windows Installation                                ║")
    print("╚════════════════════════════════════════════════════════════════╝")
    print()
    
    # Check SSH connectivity
    print("Testing SSH connectivity to PVE...")
    success, stdout, stderr = ssh_command("echo 'SSH test'")
    if not success:
        print("❌ SSH connection failed!")
        print()
        print("Please run the SSH setup first:")
        print("  bash tools/setup_pve_ssh.sh")
        print()
        sys.exit(1)
    
    print("✅ SSH connection working")
    print()
    
    # Create autounattend files
    print("Creating autounattend.xml files...")
    create_autounattend_files()
    print()
    
    # Get PVE client
    client = get_client()
    nodes = [n['node'] for n in client.nodes.get() if n.get('status') == 'online']
    if not nodes:
        print("Error: No online PVE nodes found", file=sys.stderr)
        sys.exit(1)
    
    node = nodes[0]
    print(f"Using PVE node: {node}")
    print()
    
    # Process each Windows VM
    for vm_config in WINDOWS_VMS:
        print(f"{'='*70}")
        print(f"Processing {vm_config['name']} (vmid={vm_config['vmid']})")
        print(f"{'='*70}")
        print()
        
        # Check if already a template
        resources = client.cluster.resources.get(type='vm')
        existing = {r['name']: r for r in resources}
        
        if vm_config['name'] in existing:
            vm = existing[vm_config['name']]
            if vm.get('template'):
                print(f"✅ {vm_config['name']} is already a template, skipping")
                print()
                continue
        
        # Create floppy
        if not create_floppy_on_pve(vm_config):
            print(f"❌ Failed to create floppy for {vm_config['name']}")
            print()
            continue
        
        # Attach floppy
        if not attach_floppy_to_vm(client, node, vm_config):
            print(f"❌ Failed to attach floppy to {vm_config['name']}")
            print()
            continue
        
        # Also attach VirtIO ISO for drivers
        print(f"  Attaching VirtIO ISO...")
        try:
            client.nodes(node).qemu(vm_config['vmid']).config.post(
                ide3='local:iso/virtio-win-0.1.285.iso,media=cdrom'
            )
            print(f"    ✅ VirtIO ISO attached")
        except Exception as e:
            print(f"    ⚠️  Could not attach VirtIO ISO: {e}")
        
        # Start VM
        print(f"  Starting VM...")
        if not start_vm(client, node, vm_config['vmid']):
            print(f"❌ Failed to start {vm_config['name']}")
            print()
            continue
        
        print(f"  ✅ VM started - Windows installation in progress")
        print()
    
    print()
    print("="*70)
    print("  All Windows VMs started!")
    print("="*70)
    print()
    print("Monitoring installation progress...")
    print("(This will take 30-45 minutes per VM)")
    print()
    
    # Monitor all VMs
    completed = []
    for vm_config in WINDOWS_VMS:
        vmid = vm_config['vmid']
        print(f"Monitoring {vm_config['name']} (vmid={vmid})...")
        
        if wait_for_vm_shutdown(client, node, vmid, timeout=3600):
            print(f"  ✅ {vm_config['name']} installation complete!")
            completed.append(vm_config)
        else:
            print(f"  ⚠️  {vm_config['name']} installation may still be running")
        
        print()
    
    # Convert completed VMs to templates
    if completed:
        print("="*70)
        print("  Converting completed VMs to templates...")
        print("="*70)
        print()
        
        for vm_config in completed:
            vmid = vm_config['vmid']
            print(f"Converting {vm_config['name']}...")
            try:
                client.nodes(node).qemu(vmid).config.post(template=1)
                print(f"  ✅ {vm_config['name']} converted to template")
            except Exception as e:
                print(f"  ❌ Failed to convert: {e}")
        
        print()
        print("="*70)
        print("  ✅ All Windows templates created!")
        print("="*70)
    else:
        print("No VMs completed installation yet.")
        print("Check VM status in Proxmox web UI.")


if __name__ == '__main__':
    main()
