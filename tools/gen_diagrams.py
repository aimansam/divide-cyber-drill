"""Generate div:ide cyber drill architecture diagrams by phase.

Usage:
    python3 tools/gen_diagrams.py

Outputs:
    docs/images/00-overview.png
    docs/images/01-phase0-foundations.png
    docs/images/02-phase1-one-vm-drill.png
    docs/images/03-phase2-multi-vm-sdn.png
    docs/images/04-phase3-telemetry-reports.png
    docs/images/05-phase4-polish.png
"""
import os
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle
from matplotlib.lines import Line2D

# Resolve output dir relative to this script: tools/ -> ../docs/images
_HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.normpath(os.path.join(_HERE, "..", "docs", "images"))
os.makedirs(OUT_DIR, exist_ok=True)

# ---------- Brand palette ----------
BG       = "#0f1117"
PANEL    = "#1a1f2b"
BORDER   = "#2a3142"
TEXT     = "#e6e9ef"
MUTED    = "#9aa3b2"
DIVIDE   = "#5eead4"   # teal accent (div:ide brand)
BLUE     = "#60a5fa"
RED      = "#f87171"
GREEN    = "#34d399"
AMBER    = "#fbbf24"
PURPLE   = "#a78bfa"
GREY     = "#475569"


def style_axes(ax, title, xlim=(0, 14), ylim=(0, 9.6)):
    ax.set_xlim(*xlim); ax.set_ylim(*ylim)
    ax.set_aspect("equal")
    ax.set_facecolor(BG)
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    # Title at very top
    ax.text(xlim[0] + 0.2, ylim[1] - 0.35, title,
            fontsize=15, fontweight="bold", color=TEXT,
            ha="left", va="center")
    # Accent underline just below title text — well above any bracket
    ax.add_patch(Rectangle((xlim[0] + 0.2, ylim[1] - 0.7), 2.4, 0.04,
                           color=DIVIDE, lw=0, zorder=5))


def pill(ax, x, y, w, h, text, *, color=TEXT, edge=BORDER, face=PANEL, fontsize=9, weight="normal"):
    box = FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                         boxstyle="round,pad=0.02,rounding_size=0.12",
                         linewidth=1.3, edgecolor=edge, facecolor=face)
    ax.add_patch(box)
    ax.text(x, y, text, ha="center", va="center",
            fontsize=fontsize, color=color, fontweight=weight, wrap=True)


def arrow(ax, x1, y1, x2, y2, *, color=MUTED, style="-|>", lw=1.2, ls="-", label=None, label_offset=(0, 0), label_at="mid"):
    arr = FancyArrowPatch((x1, y1), (x2, y2),
                          arrowstyle=style, mutation_scale=12,
                          color=color, linewidth=lw, linestyle=ls)
    ax.add_patch(arr)
    if label:
        if label_at == "target":
            # Label sits near the arrowhead end (useful for landing-zone clarity)
            mx, my = x1 + (x2 - x1) * 0.55, y1 + (y2 - y1) * 0.55
        elif label_at == "source":
            mx, my = x1 + (x2 - x1) * 0.25, y1 + (y2 - y1) * 0.25
        else:
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        mx += label_offset[0]; my += label_offset[1]
        ax.text(mx, my, label, fontsize=7.5, color=color,
                ha="center", va="center",
                bbox=dict(boxstyle="round,pad=0.18", fc=BG, ec=color, lw=0.6))


def bracket(ax, x, y, w, h, label, *, color=BORDER, face="#161b25", text_color=MUTED):
    box = FancyBboxPatch((x, y), w, h,
                         boxstyle="round,pad=0.02,rounding_size=0.18",
                         linewidth=1.3, edgecolor=color, facecolor=face)
    ax.add_patch(box)
    # Label sits well below the top edge to avoid clashing with rounded corner
    ax.text(x + 0.18, y + h - 0.45, label, fontsize=8.5, color=text_color,
            ha="left", va="top", fontweight="bold")


def header_band(ax, x, y, w, h, label, *, color=BORDER, face="#161b25", text_color=MUTED):
    """Header band that sits ABOVE the bracket box it labels — no overlap."""
    bar = FancyBboxPatch((x, y), w, h,
                         boxstyle="round,pad=0.02,rounding_size=0.12",
                         linewidth=1.3, edgecolor=color, facecolor=face)
    ax.add_patch(bar)
    ax.text(x + w / 2, y + h / 2, label, fontsize=9.5, color=text_color,
            ha="center", va="center", fontweight="bold")


# ============================================================
# 0. Top-level architecture overview
# ============================================================
def fig_overview():
    fig, ax = plt.subplots(figsize=(14, 10.5), facecolor=BG)
    style_axes(ax, "div:ide — Architecture Overview", xlim=(0, 14), ylim=(0, 10.5))

    # Outer Proxmox host frame — full canvas
    bracket(ax, 0.3, 0.4, 13.4, 9.7, "  Proxmox VE host  ·  all phases", color=DIVIDE, face="#0d1b22", text_color=DIVIDE)

    # === CONTROL PLANE (top section) ===
    bracket(ax, 0.5, 4.3, 13.0, 5.6, "  Control plane  ·  mgmt VLAN 192.168.0.0/24  ·  Docker Compose",
            color=BLUE, face="#0e1726", text_color=BLUE)

    # Row 1: services
    pill(ax, 1.7, 8.7, 2.0, 0.7, "div:ide-portal\n(Next.js)",  edge=DIVIDE, face="#11242b", color=DIVIDE, weight="bold")
    pill(ax, 4.0, 8.7, 2.0, 0.7, "div:ide-api\n(FastAPI)",     edge=DIVIDE, face="#11242b", color=DIVIDE, weight="bold")
    pill(ax, 6.3, 8.7, 2.0, 0.7, "orchestrator\n(RQ workers)", edge=DIVIDE, face="#11242b", color=DIVIDE, weight="bold")
    pill(ax, 8.6, 8.7, 1.6, 0.7, "postgres", edge=BORDER)
    pill(ax, 10.4, 8.7, 1.6, 0.7, "redis",    edge=BORDER)
    pill(ax, 12.2, 8.7, 1.4, 0.7, "minio",    edge=BORDER)

    # Row 2: identity / edge / observability
    pill(ax, 1.7, 7.4, 2.0, 0.7, "keycloak\n(OIDC)",            edge=PURPLE, face="#1a1330", color=PURPLE, weight="bold")
    pill(ax, 4.0, 7.4, 2.0, 0.7, "traefik\n(TLS, :443)",         edge=BLUE,   face="#0e1726", color=BLUE,   weight="bold")
    pill(ax, 6.3, 7.4, 2.0, 0.7, "guacamole\n+ noVNC",           edge=BLUE,   face="#0e1726", color=BLUE,   weight="bold")
    pill(ax, 8.6, 7.4, 3.4, 0.7, "wazuh + misp  (existing)",     edge=GREY,   face="#161b25", color=MUTED, weight="bold")
    pill(ax, 12.2, 7.4, 1.4, 0.7, "trainee\nbrowser",            edge=MUTED,  face="#1d2533", color=MUTED, weight="bold")

    # Row 3: integration legend (compact)
    pill(ax, 4.0, 6.2, 6.0, 0.55, "Prometheus + Loki + Grafana", edge=GREEN, face="#0e1f1a", color=GREEN, fontsize=9)
    pill(ax, 10.0, 6.2, 2.4, 0.55, "SOPS · age secrets",        edge=GREY,  face="#161b25", color=MUTED, fontsize=9)

    # === DRILL SDN ZONES (bottom-left) ===
    bracket(ax, 0.5, 0.6, 6.4, 3.5, "  Drill SDN zones  ·  VxLAN, one per drill",
            color=AMBER, face="#1f1a0d", text_color=AMBER)
    pill(ax, 2.0, 2.9, 1.9, 0.7, "drill-001\n10.110.0.0/24", edge=AMBER, face="#1f1a0d", color=AMBER, weight="bold")
    pill(ax, 4.3, 2.9, 1.9, 0.7, "drill-002\n10.120.0.0/24", edge=AMBER, face="#1f1a0d", color=AMBER, weight="bold")
    pill(ax, 6.6, 2.9, 1.9, 0.7, "drill-003\n10.130.0.0/24", edge=AMBER, face="#1f1a0d", color=AMBER, weight="bold")
    pill(ax, 3.7, 1.8, 6.0, 0.5, "isolated L2  ·  no cross-drill reachability", edge=BORDER, color=MUTED, fontsize=8)
    pill(ax, 3.7, 1.05, 6.0, 0.4, "linked clone VMs cloned from templates on the right", edge=BORDER, color=MUTED, fontsize=8)

    # === PROXMOX VM INVENTORY (bottom-right) ===
    bracket(ax, 7.1, 0.6, 6.4, 3.5, "  Proxmox VM inventory  ·  one-time templates",
            color=GREEN, face="#0e1f1a", text_color=GREEN)
    pill(ax, 8.8, 2.9, 1.8, 0.7, "tpl-kali\ntpl-win2022",  edge=GREEN, face="#0e1f1a", color=GREEN, weight="bold")
    pill(ax, 10.8, 2.9, 1.8, 0.7, "tpl-ubuntu\ntpl-pfsense", edge=GREEN, face="#0e1f1a", color=GREEN, weight="bold")
    pill(ax, 12.7, 2.9, 1.4, 0.7, "tpl-pcap\ncollector",  edge=GREEN, face="#0e1f1a", color=GREEN, weight="bold")
    pill(ax, 10.3, 1.8, 5.2, 0.5, "linked clones per drill  ·  ephemeral", edge=BORDER, color=MUTED, fontsize=8)
    pill(ax, 10.3, 1.05, 5.2, 0.4, "cloud-init user-data injected per drill", edge=BORDER, color=MUTED, fontsize=8)

    # === ARROW: API -> SDN (one arrow showing provisioning) ===
    arrow(ax, 4.0, 4.3, 4.0, 3.6, color=DIVIDE, label="Provisioner API", lw=1.4)

    # === LEGEND (top-left corner, below title) ===
    legend_items = [
        Line2D([0], [0], color=DIVIDE, lw=2, label="div:ide control plane"),
        Line2D([0], [0], color=AMBER,  lw=2, label="Drill SDN zones"),
        Line2D([0], [0], color=GREEN,  lw=2, label="Proxmox templates"),
        Line2D([0], [0], color=BLUE,   lw=2, label="Existing infra"),
        Line2D([0], [0], color=MUTED,  lw=2, ls="--", label="Network traffic"),
    ]
    ax.legend(handles=legend_items, loc="lower left", bbox_to_anchor=(0.32, 0.01),
              facecolor=PANEL, edgecolor=BORDER, labelcolor=TEXT, fontsize=8, framealpha=0.95, ncol=5,
              columnspacing=1.2, handlelength=1.6)

    plt.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "00-overview.png"),
                facecolor=BG, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print("✓ 00-overview.png")


# ============================================================
# 1. Phase 0 — Foundations
# ============================================================
def fig_phase0():
    fig, ax = plt.subplots(figsize=(14, 9.6), facecolor=BG)
    style_axes(ax, "Phase 0 — Foundations  ·  control plane skeleton + Proxmox API client", xlim=(0, 14), ylim=(0, 9.6))

    # Three brackets (no inline labels)
    bracket(ax, 0.5, 0.6, 13.0, 7.6, "", color=DIVIDE, face="#0e1e26")          # whole proxmox host
    bracket(ax, 0.7, 4.4, 6.3, 4.7, "", color=AMBER, face="#1f1a0d")           # control plane
    bracket(ax, 7.2, 4.4, 6.1, 4.7, "", color=BLUE,  face="#0e1726")           # existing infra
    bracket(ax, 0.7, 0.9, 6.3, 3.2, "", color=DIVIDE, face="#0e1e26")           # services
    bracket(ax, 7.2, 0.9, 6.1, 3.2, "", color=GREY,  face="#161b25")           # trainee/operator

    # Section labels (placed in their own bands, not inside the brackets)
    header_band(ax, 0.7, 8.5, 6.3, 0.5, "Control plane  ·  Docker Compose stack", color=DIVIDE, face="#0e1e26", text_color=DIVIDE)
    header_band(ax, 7.2, 8.5, 6.1, 0.5, "Existing infra (preview)",              color=BLUE,  face="#0e1726", text_color=BLUE)

    pill(ax, 3.85, 3.7, 4.0, 0.4, "Proxmox VE host (out of band)", edge=AMBER, face="#1f1a0d", color=AMBER, fontsize=9.5, weight="bold")
    pill(ax, 10.25,3.7, 4.0, 0.4, "Trainee / operator",             edge=GREY,  face="#161b25", color=MUTED, fontsize=9.5, weight="bold")

    # === Control plane content ===
    pill(ax, 2.0, 7.7, 2.0, 0.7, "div:ide-api\n(FastAPI)",     edge=DIVIDE, face="#11242b", color=DIVIDE, weight="bold", fontsize=10)
    pill(ax, 4.5, 7.7, 1.6, 0.7, "postgres 16",       edge=BORDER, fontsize=10)
    pill(ax, 6.5, 7.7, 1.6, 0.7, "redis 7",           edge=BORDER, fontsize=10)
    pill(ax, 2.0, 6.6, 2.0, 0.55, "main.py + routers/", edge=BORDER, color=MUTED, fontsize=9)
    pill(ax, 4.5, 6.6, 1.6, 0.55, "drills, scenarios,\nusers", edge=BORDER, color=MUTED, fontsize=8.5)
    pill(ax, 6.5, 6.6, 1.6, 0.55, "RQ queue\nprovisioner",     edge=BORDER, color=MUTED, fontsize=8.5)
    pill(ax, 4.0, 5.6, 5.6, 0.55, "GET /healthz  ·  POST /drills (stub)  ·  Proxmox smoke",
         edge=GREEN, face="#0e1f1a", color=GREEN, fontsize=9.5)

    # === Existing infra preview (Phase 0) ===
    pill(ax, 8.5, 7.7, 1.6, 0.7, "traefik\n(TLS :443)", edge=BLUE, face="#0e1726", color=BLUE, fontsize=10)
    pill(ax, 10.4,7.7, 1.6, 0.7, "minio\n(artifacts)", edge=BORDER, fontsize=10)
    pill(ax, 8.5, 6.6, 1.6, 0.55, "self-signed\ndev cert", edge=BORDER, color=MUTED, fontsize=8.5)
    pill(ax, 10.4,6.6, 1.6, 0.55, "drill-001/\nPCAP, logs", edge=BORDER, color=MUTED, fontsize=8.5)
    pill(ax, 9.7, 5.6, 3.0, 0.55, "Makefile:  make up · logs · drill-smoke",
         edge=GREY, face="#161b25", color=MUTED, fontsize=9)

    # === Proxmox target ===
    pill(ax, 3.85, 2.6, 4.0, 0.85, "Proxmox VE 8.x\nhttps://pve.local:8006",
         edge=AMBER, face="#1f1a0d", color=AMBER, weight="bold", fontsize=10)
    pill(ax, 3.85, 1.55, 4.0, 0.5, "PVE token  ·  divide@pve  (PVEVMAdmin)",
         edge=BORDER, color=MUTED, fontsize=8.5)

    # === Trainee ===
    pill(ax, 10.25, 2.6, 2.4, 0.85, "operator browser",
         edge=MUTED, face="#1d2533", color=MUTED, fontsize=10)
    pill(ax, 10.25, 1.55, 2.4, 0.5, "logs only  ·  no drills yet",
         edge=BORDER, color=MUTED, fontsize=8.5)

    # === Arrows ===
    arrow(ax, 2.0, 5.3, 3.85, 3.0, color=AMBER, label="REST  /api2/json", lw=1.3)
    arrow(ax, 10.25, 2.55, 8.5, 7.4, color=MUTED, ls="--", label="HTTPS")

    plt.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "01-phase0-foundations.png"),
                facecolor=BG, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print("✓ 01-phase0-foundations.png")


# ============================================================
# 2. Phase 1 — One-VM drill end-to-end
# ============================================================
def fig_phase1():
    fig, ax = plt.subplots(figsize=(14, 9.6), facecolor=BG)
    style_axes(ax, "Phase 1 — One-VM drill end-to-end  ·  vsftpd 2.3.4 scenario", xlim=(0, 14), ylim=(0, 9.6))

    # Section brackets (no inline labels)
    bracket(ax, 0.5, 4.6, 13.0, 3.6, "", color=DIVIDE, face="#0e1e26")  # control plane
    bracket(ax, 0.5, 0.6, 13.0, 3.7, "", color=MUTED,  face="#161b25")  # trainee/infra row
    # drill VM bracket
    bracket(ax, 8.5, 5.0, 5.1, 4.3, "", color=AMBER, face="#1f1a0d")

    # Header bands identifying each region
    header_band(ax, 0.5, 8.8, 13.0, 0.5, "Proxmox host  ·  mgmt VLAN 192.168.0.0/24", color=DIVIDE, face="#0d1b22", text_color=DIVIDE)
    header_band(ax, 0.5, 8.2,  7.9, 0.45, "Control plane  ·  Docker Compose stack",    color=DIVIDE, face="#0e1e26", text_color=DIVIDE)
    header_band(ax, 8.5, 8.2,  5.1, 0.45, "Drill network (single VxLAN)",              color=AMBER, face="#1f1a0d", text_color=AMBER)
    header_band(ax, 0.5, 4.1,  7.9, 0.4,  "Trainee view",                              color=BLUE,  face="#0e1726", text_color=BLUE)
    header_band(ax, 8.5, 4.1,  5.1, 0.4,  "Existing infra (Wazuh auto-enroll)",       color=GREY,  face="#161b25", text_color=MUTED)

    # === Control plane pills ===
    pill(ax, 1.7, 7.5, 1.8, 0.7, "div:ide-portal", edge=DIVIDE, face="#11242b", color=DIVIDE, weight="bold")
    pill(ax, 3.9, 7.5, 1.8, 0.7, "div:ide-api",    edge=DIVIDE, face="#11242b", color=DIVIDE, weight="bold")
    pill(ax, 6.1, 7.5, 1.6, 0.7, "orchestrator",   edge=DIVIDE, face="#11242b", color=DIVIDE, weight="bold")
    pill(ax, 2.5, 6.4, 1.6, 0.55, "postgres", edge=BORDER, color=MUTED, fontsize=9)
    pill(ax, 4.5, 6.4, 1.6, 0.55, "redis",    edge=BORDER, color=MUTED, fontsize=9)
    pill(ax, 6.5, 6.4, 1.6, 0.55, "minio",    edge=BORDER, color=MUTED, fontsize=9)
    pill(ax, 2.0, 5.4, 1.6, 0.5, "scenarios\nlist",     edge=BORDER, color=MUTED, fontsize=8.5)
    pill(ax, 4.0, 5.4, 1.6, 0.5, "POST /drills",        edge=BORDER, color=MUTED, fontsize=8.5)
    pill(ax, 6.0, 5.4, 1.6, 0.5, "provisioner\n+ ansible", edge=BORDER, color=MUTED, fontsize=8.5)

    # === Drill VM ===
    pill(ax, 10.0, 7.5, 2.6, 0.9, "tpl-ubuntu-2204\n(linked clone)",
         edge=AMBER, face="#1f1a0d", color=AMBER, weight="bold", fontsize=10)
    pill(ax, 10.0, 6.4, 2.6, 0.55, "vsftpd 2.3.4\n(scenario patch)", edge=BORDER, color=MUTED, fontsize=8.5)
    pill(ax, 10.0, 5.6, 2.6, 0.55, "qemu-guest-agent",                 edge=BORDER, color=MUTED, fontsize=8.5)
    pill(ax, 12.0, 5.0, 1.4, 0.5,  "~ 3 min\nboot -> ready",           edge=GREEN, face="#0e1f1a", color=GREEN, fontsize=8.5)

    # === Existing infra ===
    pill(ax, 10.0, 2.7, 2.6, 0.85, "Wazuh manager", edge=GREY, face="#161b25", color=MUTED, weight="bold")
    pill(ax, 10.0, 1.6, 2.6, 0.55, "auto-create drill-<id>\nagent group",
         edge=BORDER, color=MUTED, fontsize=8.5)

    # === Trainee view ===
    pill(ax, 2.0, 2.7, 2.6, 0.85, "noVNC console\n(Guacamole)", edge=BLUE, face="#0e1726", color=BLUE, weight="bold")
    pill(ax, 5.0, 2.7, 2.6, 0.85, "live artifacts\npanel",        edge=BLUE, face="#0e1726", color=BLUE, weight="bold")
    pill(ax, 2.0, 1.6, 2.6, 0.55, "Start / Stop drill", edge=BORDER, color=MUTED, fontsize=8.5)
    pill(ax, 5.0, 1.6, 2.6, 0.55, "PCAP viewer",       edge=BORDER, color=MUTED, fontsize=8.5)

    # === Arrows ===
    # Short control-plane flow (left to right)
    arrow(ax, 1.7, 7.15, 3.9, 7.15,  color=DIVIDE, label="REST")
    arrow(ax, 3.9, 7.15, 6.1, 7.15,  color=DIVIDE, label="queue")
    arrow(ax, 6.1, 7.15, 10.0, 7.15, color=AMBER,  label="clone + boot", label_offset=(-1.0, 0.45))
    # cloud-init: short diagonal from provisioner area to qemu-guest-agent pill only
    # (origin moved LEFT and DOWN to avoid crossing vsftpd pill)
    arrow(ax, 7.0, 5.4, 10.0, 5.6, color=AMBER, ls="--", label="cloud-init",
          label_offset=(0.7, -0.4), label_at="source")
    # Wazuh enroll: vertical, well below the header band
    arrow(ax, 11.3, 4.9, 11.3, 2.7, color=GREEN, label="Wazuh enroll", label_offset=(-0.7, -0.4))

    # VNC: right-angle path. Horizontal segment BELOW the trainee header band.
    arrow(ax, 10.0, 7.5, 10.0, 3.4, color=MUTED, ls=":")
    arrow(ax, 10.0, 3.4, 2.0, 3.4, color=MUTED, ls=":", label="VNC", label_offset=(0, 0.5))
    arrow(ax, 2.0, 3.4, 2.0, 3.1, color=MUTED, ls=":")

    # artifacts: same pattern but on a different y to avoid VNC label collision
    arrow(ax, 10.0, 7.5, 10.0, 3.2, color=MUTED, ls=":")
    arrow(ax, 10.0, 3.2, 5.0, 3.2, color=MUTED, ls=":", label="artifacts", label_offset=(0, 0.5))
    arrow(ax, 5.0, 3.2, 5.0, 3.1, color=MUTED, ls=":")

    plt.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "02-phase1-one-vm-drill.png"),
                facecolor=BG, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print("✓ 02-phase1-one-vm-drill.png")


# ============================================================
# 3. Phase 2 — Multi-VM + SDN
# ============================================================
def fig_phase2():
    fig, ax = plt.subplots(figsize=(14, 9.6), facecolor=BG)
    style_axes(ax, "Phase 2 — Multi-VM + SDN  ·  isolated VxLAN per drill", xlim=(0, 14), ylim=(0, 9.6))

    # Brackets (no labels)
    bracket(ax, 0.4, 7.1, 13.2, 2.0, "", color=DIVIDE, face="#0e1e26")  # control plane band
    bracket(ax, 0.4, 4.1, 6.4, 2.7, "", color=AMBER,  face="#1f1a0d")   # Drill A
    bracket(ax, 7.2, 4.1, 6.4, 2.7, "", color=AMBER,  face="#1f1a0d")   # Drill B
    bracket(ax, 0.4, 1.5, 6.4, 2.3, "", color=GREEN,  face="#0e1f1a")   # telemetry / egress
    bracket(ax, 7.2, 1.5, 6.4, 2.3, "", color=GREEN,  face="#0e1f1a")   # pcap tap
    bracket(ax, 0.4, 0.1, 13.2, 1.2, "", color=GREY,   face="#161b25")  # existing infra row

    # Header bands
    header_band(ax, 0.4, 8.85, 13.2, 0.5, "Proxmox host  ·  mgmt VLAN",  color=DIVIDE, face="#0d1b22", text_color=DIVIDE)
    header_band(ax, 0.4, 8.20, 13.2, 0.5, "Control plane  ·  mgmt VLAN", color=DIVIDE, face="#0e1e26", text_color=DIVIDE)
    header_band(ax, 0.4, 6.55, 6.4, 0.4,  "Drill A  ·  VxLAN vni 10001", color=AMBER, face="#1f1a0d", text_color=AMBER)
    header_band(ax, 7.2, 6.55, 6.4, 0.4,  "Drill B  ·  VxLAN vni 10002", color=AMBER, face="#1f1a0d", text_color=AMBER)
    header_band(ax, 0.4, 3.45, 6.4, 0.4,  "Telemetry egress (egress-only)", color=GREEN, face="#0e1f1a", text_color=GREEN)
    header_band(ax, 7.2, 3.45, 6.4, 0.4,  "PCAP span-port tap",              color=GREEN, face="#0e1f1a", text_color=GREEN)
    header_band(ax, 0.4, 0.90, 13.2, 0.4, "Existing infra",                color=GREY,  face="#161b25", text_color=MUTED)

    # Control plane row
    pill(ax, 1.7, 7.7, 1.6, 0.5, "portal",     edge=DIVIDE, face="#11242b", color=DIVIDE)
    pill(ax, 3.5, 7.7, 1.6, 0.5, "api",        edge=DIVIDE, face="#11242b", color=DIVIDE)
    pill(ax, 5.3, 7.7, 1.6, 0.5, "orch.",      edge=DIVIDE, face="#11242b", color=DIVIDE)
    pill(ax, 7.1, 7.7, 1.4, 0.5, "postgres",   edge=BORDER)
    pill(ax, 8.7, 7.7, 1.4, 0.5, "redis",      edge=BORDER)
    pill(ax, 10.3,7.7, 1.4, 0.5, "minio",      edge=BORDER)
    pill(ax, 12.0,7.7, 1.4, 0.5, "guac/noVNC", edge=BLUE, face="#0e1726", color=BLUE)
    pill(ax, 3.5, 7.25, 5.4, 0.35, "scenario engine  ·  inject runner", edge=BORDER, color=MUTED, fontsize=8)

    # Drill A
    pill(ax, 2.0, 5.7, 1.7, 0.7, "Kali\n(red)",        edge=RED,   face="#260f12", color=RED,   weight="bold", fontsize=9.5)
    pill(ax, 4.0, 5.7, 1.7, 0.7, "pfsense\n(fw)",      edge=GREEN, face="#0e1f1a", color=GREEN, weight="bold", fontsize=9.5)
    pill(ax, 6.0, 5.7, 1.7, 0.7, "Win2022 DC\n(blue)", edge=BLUE,  face="#0e1726", color=BLUE,  weight="bold", fontsize=9.5)
    pill(ax, 4.0, 4.55, 1.7, 0.45, "Ubuntu web\n(dmz)", edge=BLUE,  face="#0e1726", color=BLUE,  weight="bold", fontsize=8.5)
    pill(ax, 4.0, 4.20, 5.4, 0.35, "VLAN 110 corp  ·  VLAN 120 dmz", edge=BORDER, color=MUTED, fontsize=8)

    # Drill B
    pill(ax, 8.7, 5.7, 1.7, 0.7, "Kali",        edge=RED,   face="#260f12", color=RED,   weight="bold", fontsize=9.5)
    pill(ax, 10.7,5.7, 1.7, 0.7, "Win2022",     edge=BLUE,  face="#0e1726", color=BLUE,  weight="bold", fontsize=9.5)
    pill(ax, 12.5,5.7, 1.7, 0.7, "Ubuntu srv",  edge=BLUE,  face="#0e1726", color=BLUE,  weight="bold", fontsize=9.5)
    pill(ax, 10.7,4.20, 4.0, 0.35, "VLAN 130  ·  red", edge=BORDER, color=MUTED, fontsize=8)

    # L2 isolation badge (between Drill A and Drill B) — pushed higher so it doesn't overlap Win2022
    pill(ax, 6.85, 4.55, 0.5, 0.4, "L2\nisolated", edge=RED, face="#260f12", color=RED, fontsize=7.5)

    # Telemetry / PCAP
    pill(ax, 3.6, 2.9, 4.0, 0.55, "routed telemetry\n(egress-only firewall)",
         edge=GREEN, face="#0e1f1a", color=GREEN, fontsize=9.5)
    pill(ax, 10.4, 2.9, 4.0, 0.55, "span port  ·  tcpdump\n-> MinIO",
         edge=GREEN, face="#0e1f1a", color=GREEN, fontsize=9.5)

    # Existing infra row
    pill(ax, 4.0, 0.55, 2.0, 0.5, "Wazuh mgr",        edge=GREY, face="#161b25", color=MUTED, weight="bold", fontsize=9)
    pill(ax, 6.4, 0.55, 2.0, 0.5, "MISP",             edge=GREY, face="#161b25", color=MUTED, weight="bold", fontsize=9)
    pill(ax, 8.8, 0.55, 2.0, 0.5, "Prometheus + Loki", edge=GREY, face="#161b25", color=MUTED, weight="bold", fontsize=9)
    pill(ax, 11.2,0.55, 2.0, 0.5, "Grafana",          edge=GREY, face="#161b25", color=MUTED, weight="bold", fontsize=9)

    # Arrows — labels pushed away from header bands
    # clone arrows: shorter, label pushed left/up
    arrow(ax, 3.5, 7.45, 2.0, 6.1,  color=AMBER, label="clone", label_offset=(-0.5, 0.3), label_at="source")
    arrow(ax, 5.3, 7.45, 10.7, 6.1, color=AMBER, label="clone", label_offset=( 0.5, 0.3), label_at="source")
    # syslog/agent: arrow goes from VM down to telemetry box.
    # Place label at TARGET (top of telemetry box) — clear of the header band.
    arrow(ax, 4.0, 4.0, 3.6, 3.25, color=GREEN, label="syslog", label_offset=(-0.5, 0.5), label_at="target")
    # PCAP: label at target
    arrow(ax, 10.7, 4.0, 10.4, 3.25, color=GREEN, label="PCAP", label_offset=(0.5, 0.5), label_at="target")
    # alerts: label at target (top of Wazuh box)
    arrow(ax, 3.6, 2.6, 4.0, 0.85, color=GREEN, label="alerts", label_offset=(-0.5, -0.4), label_at="source")
    # IOCs: label at target
    arrow(ax, 10.4, 2.6, 6.4, 0.85, color=GREEN, label="IOCs", label_offset=(0.5, -0.4), label_at="source")

    plt.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "03-phase2-multi-vm-sdn.png"),
                facecolor=BG, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print("✓ 03-phase2-multi-vm-sdn.png")


# ============================================================
# 4. Phase 3 — Telemetry & reports
# ============================================================
def fig_phase3():
    fig, ax = plt.subplots(figsize=(14, 9.6), facecolor=BG)
    style_axes(ax, "Phase 3 — Telemetry & after-action reports", xlim=(0, 14), ylim=(0, 9.6))

    # Brackets (no labels)
    bracket(ax, 0.3, 4.8, 4.0, 4.2, "", color=AMBER, face="#1f1a0d")  # Drill VMs
    bracket(ax, 4.6, 4.8, 4.6, 4.2, "", color=BLUE,  face="#0e1726")  # Wazuh
    bracket(ax, 9.5, 6.4, 4.2, 2.6, "", color=GREEN, face="#0e1f1a")  # PCAP tap
    bracket(ax, 4.6, 0.4, 9.1, 4.0, "", color=DIVIDE, face="#0e1e26") # report builder

    # Header bands
    header_band(ax, 0.3, 8.6, 4.0, 0.4, "Drill VMs  ·  per-drill agents",      color=AMBER, face="#1f1a0d", text_color=AMBER)
    header_band(ax, 4.6, 8.6, 4.6, 0.4, "Wazuh  ·  group=drill-<id>",          color=BLUE,  face="#0e1726", text_color=BLUE)
    header_band(ax, 9.5, 8.6, 4.2, 0.4, "PCAP / artifact tap",                color=GREEN, face="#0e1f1a", text_color=GREEN)
    header_band(ax, 4.6, 4.0, 9.1, 0.4, "div:ide report builder  ·  on drill teardown", color=DIVIDE, face="#0e1e26", text_color=DIVIDE)

    # Drill VMs
    pill(ax, 2.3, 7.9, 1.7, 0.55, "kali",       edge=RED,   face="#260f12", color=RED,   weight="bold")
    pill(ax, 2.3, 7.1, 1.7, 0.55, "win2022",    edge=BLUE,  face="#0e1726", color=BLUE,  weight="bold")
    pill(ax, 2.3, 6.3, 1.7, 0.55, "ubuntu srv", edge=BLUE,  face="#0e1726", color=BLUE,  weight="bold")
    pill(ax, 2.3, 5.5, 1.7, 0.55, "pfsense",    edge=GREEN, face="#0e1f1a", color=GREEN, weight="bold")
    pill(ax, 2.3, 4.95, 1.7, 0.4,  "Wazuh agent + Sysmon", edge=BORDER, color=MUTED, fontsize=8)

    # Wazuh
    pill(ax, 6.9, 7.9, 1.8, 0.6,  "manager",           edge=BLUE, face="#0e1726", color=BLUE, weight="bold")
    pill(ax, 6.9, 7.0, 1.8, 0.55, "rules + decoders",  edge=BORDER, color=MUTED, fontsize=8.5)
    pill(ax, 6.9, 6.1, 1.8, 0.55, "alerts index",      edge=BORDER, color=MUTED, fontsize=8.5)
    pill(ax, 6.9, 5.2, 1.8, 0.55, "drill-<id>\nagent group", edge=BORDER, color=MUTED, fontsize=8.5)

    # PCAP tap
    pill(ax, 11.6, 7.6, 1.8, 0.6,  "tpl-tinycore\ntcpdump", edge=GREEN, face="#0e1f1a", color=GREEN, weight="bold")
    pill(ax, 11.6, 6.7, 1.8, 0.55, "rotated .pcap\n-> MinIO", edge=BORDER, color=MUTED, fontsize=8.5)
    pill(ax, 11.6, 5.5, 1.8, 0.4,  "span port  ·  drill VNet", edge=BORDER, color=MUTED, fontsize=8)

    # Report builder
    pill(ax, 6.0, 3.3, 2.2, 0.7,  "extract IOCs\nfrom PCAP",       edge=DIVIDE, face="#11242b", color=DIVIDE, fontsize=9.5, weight="bold")
    pill(ax, 8.4, 3.3, 2.2, 0.7,  "extract alerts\nfrom Wazuh",    edge=DIVIDE, face="#11242b", color=DIVIDE, fontsize=9.5, weight="bold")
    pill(ax, 10.8,3.3, 2.2, 0.7,  "timeline + injects\ncorrelate", edge=DIVIDE, face="#11242b", color=DIVIDE, fontsize=9.5, weight="bold")
    pill(ax, 6.0, 2.3, 2.2, 0.55, "IPs, domains, URLs", edge=BORDER, color=MUTED, fontsize=8.5)
    pill(ax, 8.4, 2.3, 2.2, 0.55, "MITRE TTP tags",     edge=BORDER, color=MUTED, fontsize=8.5)
    pill(ax, 10.8,2.3, 2.2, 0.55, "detection deltas",  edge=BORDER, color=MUTED, fontsize=8.5)
    pill(ax, 6.0, 1.4, 4.0, 0.6,  "-> MISP event  (drill:<id>, tlp:amber)",
         edge=PURPLE, face="#1a1330", color=PURPLE, weight="bold", fontsize=9.5)
    pill(ax, 10.6,1.4, 2.8, 0.6,  "-> PDF AAR (MinIO)",
         edge=DIVIDE, face="#11242b", color=DIVIDE, weight="bold", fontsize=9.5)

    # Arrows (clean, no overlap with pills)
    arrow(ax, 3.2, 7.9,  5.85, 7.9,  color=BLUE,  label="agents", label_offset=(0, 0.3))
    arrow(ax, 11.6, 6.3, 7.2, 3.7,  color=DIVIDE, ls="--", label="PCAP meta", label_offset=(0.4, 0))
    arrow(ax, 8.4, 6.95, 7.2, 3.7,  color=DIVIDE, label="alerts", label_offset=(0, 0.3))
    arrow(ax, 11.6, 7.0, 5.85, 3.7, color=GREEN,  ls=":", label="span", label_offset=(0, 0.3))
    arrow(ax, 7.95, 1.4, 7.95, 1.0, color=PURPLE, label="publish", label_offset=(0.4, 0))
    arrow(ax, 11.8, 1.4, 11.8, 1.0, color=DIVIDE, label="store",  label_offset=(0.4, 0))

    plt.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "04-phase3-telemetry-reports.png"),
                facecolor=BG, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print("✓ 04-phase3-telemetry-reports.png")


# ============================================================
# 5. Phase 4 — Polish
# ============================================================
def fig_phase4():
    fig, ax = plt.subplots(figsize=(14, 9.6), facecolor=BG)
    style_axes(ax, "Phase 4 — Polish  ·  RBAC, scheduling, scenarios marketplace", xlim=(0, 14), ylim=(0, 9.6))

    # Brackets (no labels)
    bracket(ax, 0.3, 6.4, 13.4, 2.6, "", color=PURPLE, face="#1a1330")  # identity band
    bracket(ax, 0.3, 3.5, 4.4, 2.6, "", color=AMBER,  face="#1f1a0d")  # scheduled drills
    bracket(ax, 5.0, 3.5, 4.4, 2.6, "", color=DIVIDE, face="#0e1e26")  # marketplace
    bracket(ax, 9.7, 3.5, 4.0, 2.6, "", color=GREEN,  face="#0e1f1a")  # observability
    bracket(ax, 0.3, 0.4, 13.4, 2.9, "", color=DIVIDE, face="#0e1e26") # lifecycle strip

    # Header bands
    header_band(ax, 0.3, 8.6, 13.4, 0.4, "Identity & access  ·  Keycloak realm: divide", color=PURPLE, face="#1a1330", text_color=PURPLE)
    header_band(ax, 0.3, 5.85, 4.4, 0.4, "Scheduled drills",          color=AMBER,  face="#1f1a0d", text_color=AMBER)
    header_band(ax, 5.0, 5.85, 4.4, 0.4, "Scenarios marketplace",      color=DIVIDE, face="#0e1e26", text_color=DIVIDE)
    header_band(ax, 9.7, 5.85, 4.0, 0.4, "Observability",              color=GREEN,  face="#0e1f1a", text_color=GREEN)
    header_band(ax, 0.3, 2.85, 13.4, 0.4, "div:ide — full lifecycle",  color=DIVIDE, face="#0e1e26", text_color=DIVIDE)

    # Roles row
    roles = [("admin",      PURPLE),
             ("drill-lead", BLUE),
             ("blue team",  GREEN),
             ("red team",   RED),
             ("observer",   MUTED)]
    for i, (name, col) in enumerate(roles):
        x = 1.4 + i * 2.5
        pill(ax, x, 7.8, 2.0, 0.55, name, edge=col, face="#0e1e26", color=col, weight="bold")
    pill(ax, 7.0, 7.2, 6.0, 0.4, "OIDC  ·  SSO  ·  scoped Proxmox tokens", edge=BORDER, color=MUTED, fontsize=8.5)

    # Scheduled drills
    pill(ax, 2.5, 5.05, 3.6, 0.55, "RQ scheduler  ·  cron",   edge=BORDER, color=MUTED)
    pill(ax, 2.5, 4.30, 3.6, 0.55, "scenario catalog",         edge=BORDER, color=MUTED)
    pill(ax, 2.5, 3.55, 3.6, 0.55, "TTL / capacity guard",     edge=BORDER, color=MUTED)

    # Marketplace
    pill(ax, 7.2, 5.05, 3.6, 0.55, "import / export YAML", edge=DIVIDE, face="#11242b", color=DIVIDE)
    pill(ax, 7.2, 4.30, 3.6, 0.55, "versioned + signed",   edge=DIVIDE, face="#11242b", color=DIVIDE)
    pill(ax, 7.2, 3.55, 3.6, 0.55, "multi-tenant orgs",    edge=DIVIDE, face="#11242b", color=DIVIDE)

    # Observability
    pill(ax, 11.7, 5.05, 3.2, 0.55, "Prometheus", edge=GREEN, face="#0e1f1a", color=GREEN, weight="bold")
    pill(ax, 11.7, 4.30, 3.2, 0.55, "Loki",       edge=GREEN, face="#0e1f1a", color=GREEN, weight="bold")
    pill(ax, 11.7, 3.55, 3.2, 0.55, "Grafana",    edge=GREEN, face="#0e1f1a", color=GREEN, weight="bold")

    # Lifecycle strip
    states = ["DRAFT", "SCHEDULED", "PROVISIONING", "LIVE", "PAUSED", "TEARING_DOWN", "REPORTED", "ARCHIVED"]
    for i, s in enumerate(states):
        x = 1.0 + i * 1.6
        col = AMBER if s == "LIVE" else BLUE if s in ("PROVISIONING", "REPORTED") else DIVIDE if s in ("DRAFT", "SCHEDULED", "ARCHIVED") else MUTED
        pill(ax, x, 1.95, 1.4, 0.55, s, edge=col, face="#0e1e26", color=col, weight="bold", fontsize=9)
        if i < len(states) - 1:
            arrow(ax, x + 0.75, 1.95, x + 1.45, 1.95, color=MUTED, lw=1.0)

    pill(ax, 7.0, 1.05, 10.0, 0.5,
         "audit_log  ·  Proxmox events  ·  Wazuh rule correlation  ·  AAR PDF in MinIO",
         edge=BORDER, color=MUTED, fontsize=9)

    plt.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "05-phase4-polish.png"),
                facecolor=BG, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print("✓ 05-phase4-polish.png")


if __name__ == "__main__":
    fig_overview()
    fig_phase0()
    fig_phase1()
    fig_phase2()
    fig_phase3()
    fig_phase4()
    print("\nDone.")
