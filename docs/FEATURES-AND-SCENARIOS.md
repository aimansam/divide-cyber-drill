# Features & Scenario Specification

This guide details all cyber-range capabilities, the declarative Scenario YAML specification, multi-team competitions, and scoring models.

---

## 1. Scenario YAML Specification

Drill scenarios are written in human-readable YAML. Each scenario defines network topologies, target assets, provisioning rules, flags, and team assignments.

### Minimal Example (`red-vs-blue-baseline.scenario.yaml`)

```yaml
schema_version: "1.0"
metadata:
  id: "scenario-rvb-01"
  name: "Red vs Blue Baseline"
  description: "Enterprise DMZ + Internal network with file server and firewall targets."
  difficulty: "intermediate"
  estimated_minutes: 60

networks:
  - id: "net-dmz"
    name: "DMZ Network"
    cidr: "10.100.1.0/24"
    bridge: "vmbr10" # Mapped to Linux Bridge or SDN vnet
  - id: "net-internal"
    name: "Internal LAN"
    cidr: "10.100.2.0/24"
    bridge: "vmbr20"

assets:
  - id: "router-fw"
    name: "Boundary Firewall"
    role: "firewall"
    template_vmid: 9000
    cores: 2
    memory_mb: 2048
    networks:
      - network_id: "net-dmz"
        ip: "10.100.1.1"
      - network_id: "net-internal"
        ip: "10.100.2.1"

  - id: "target-fileserver"
    name: "Corporate File Server"
    role: "target"
    template_vmid: 9001
    cores: 2
    memory_mb: 4096
    networks:
      - network_id: "net-internal"
        ip: "10.100.2.50"
    cloud_init:
      user: "operator"
      ssh_authorized_keys:
        - "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5..."

flags:
  - id: "flag-root-compromise"
    title: "Root Shell on File Server"
    asset_id: "target-fileserver"
    side: "red"
    base_points: 100
    decay_window_minutes: 30
    flag_pattern: "DIVIDE{root_fs_captured_.*}"

teams:
  - id: "team-red"
    name: "Red Attackers"
    role: "red"
  - id: "team-blue"
    name: "Blue Defenders"
    role: "blue"
```

---

## 2. Cyber-Range Core Capabilities

### 2.1 Multi-VM Asset Spawning & Networking
- **Bridge & SDN Auto-Provisioning**: When a drill starts, the runner creates the declared virtual networks on the PVE cluster (`vmbr*` or SDN vnets).
- **Fast Cloning**: Target VMs are linked-cloned from immutable base templates (`tpl-*`), booting in seconds.
- **Cloud-Init Customization**: Automatically injects dynamic user credentials, SSH keys, IP addressing, and plant flags on boot.

### 2.2 Live in-Browser noVNC Console
- Direct browser access to VM graphical screens and text consoles without direct SSH or exposing Proxmox credentials.
- Integrated clipboard synchronization and interactive terminal support via canvas rendering.

### 2.3 Flag Submission & Scoring Engine
- **Flag Planting**: Runner places dynamic flag tokens inside assets at scenario launch (e.g. in `/root/flag.txt` or registry keys).
- **Time-Decay Formula**:
  $$\text{Points} = \text{Base} \times \max\left(0.2, 1 - \frac{\text{elapsed\_time}}{\text{decay\_window}}\right)$$
- First-blood bonuses and capture breakdown logs included in the after-action report.

### 2.4 Multi-Team Exercises & Live Leaderboard
- Run simultaneous parallel drill environments for multiple teams against the same baseline scenario.
- Live real-time leaderboard polling every 5 seconds or streaming updates via SSE.

### 2.5 Range Templates & Instant Reset
- **Template Snapshotting**: Admins can capture a finished/configured run as a permanent immutable snapshot (`Template`).
- **One-Click Range Reset**: Instantly tear down compromised assets and re-spawn a fresh, clean drill environment in under 45 seconds.

### 2.6 Blue-Team SOC View & Kill-Chain Telemetry
- Real-time event timeline visualizing MITRE ATT&CK kill-chain stages (Initial Access, Privilege Escalation, Lateral Movement, Data Exfiltration).
- Event stream captures audit trail, flag submissions, runner lifecycles, and simulated alert telemetry.
