"""WireGuard VPN config generation service.

Generates per-user WireGuard client configs entirely in Python —
no ``wg`` binary required on the API container.

Key derivation: HMAC-SHA256(key=DIVIDE_WG_PEER_SECRET, msg=peer_id)
clamped to a valid Curve25519 scalar.  The public key is derived via
the Montgomery ladder (RFC 7748 §5).  A user always gets the same
keypair from the same peer_id; rotating DIVIDE_WG_PEER_SECRET
invalidates all configs at once.

IP allocation: each user gets a /32 in DIVIDE_WG_SUBNET based on
their peer_index (server = index 0 → .1, clients start at .2).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import uuid

from app.core.config import settings


# ---------------------------------------------------------------------------
# Curve25519 key derivation
# ---------------------------------------------------------------------------

def _clamp(raw: bytes) -> bytearray:
    k = bytearray(raw[:32])
    k[0] &= 248; k[31] &= 127; k[31] |= 64
    return k


def _mul_base(k: int) -> int:
    """Montgomery ladder: k * G on Curve25519, returns x-coordinate."""
    p = (1 << 255) - 19
    x2, z2, x3, z3, swap = 1, 0, 9, 1, 0
    for i in range(254, -1, -1):
        bit = (k >> i) & 1
        swap ^= bit
        if swap:
            x2, x3 = x3, x2
            z2, z3 = z3, z2
        swap = bit
        A = (x2 + z2) % p; AA = A * A % p
        B = (x2 - z2) % p; BB = B * B % p
        E = (AA - BB) % p
        C = (x3 + z3) % p
        D = (x3 - z3) % p
        DA = D * A % p; CB = C * B % p
        x3 = pow(DA + CB, 2, p)
        z3 = 9 * pow(DA - CB, 2, p) % p
        x2 = AA * BB % p
        z2 = (121665 * E + AA) % p * E % p
    if swap:
        x2, x3 = x3, x2
    return x2 * pow(z2, p - 2, p) % p


def _keypair(peer_id: str, secret: str) -> tuple[str, str]:
    """Return (privkey_b64, pubkey_b64) for peer_id."""
    raw = hmac.new(secret.encode(), peer_id.encode(), hashlib.sha256).digest()
    priv = _clamp(raw)
    pub  = _mul_base(int.from_bytes(priv, "little")).to_bytes(32, "little")
    return base64.b64encode(bytes(priv)).decode(), base64.b64encode(pub).decode()


# ---------------------------------------------------------------------------
# IP allocation
# ---------------------------------------------------------------------------

def _host_ip(index: int, subnet: str) -> str:
    hosts = list(ipaddress.IPv4Network(subnet, strict=False).hosts())
    if index >= len(hosts):
        raise ValueError(f"VPN subnet {subnet} exhausted at index {index}")
    return str(hosts[index])


def server_ip(subnet: str | None = None) -> str:
    return _host_ip(0, subnet or settings.wg_subnet)


def client_ip(peer_index: int, subnet: str | None = None) -> str:
    return _host_ip(peer_index, subnet or settings.wg_subnet)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def assign_peer_id() -> str:
    """Generate a new stable UUID for a user's WireGuard peer."""
    return str(uuid.uuid4())


def build_client_config(
    *,
    peer_id: str,
    peer_index: int,
    server_pubkey: str,
    subnet: str | None = None,
    allowed_ips: str | None = None,
    dns: str | None = None,
    host: str | None = None,
    port: int | None = None,
    peer_secret: str | None = None,
) -> str:
    """Render a WireGuard client .conf for the given peer."""
    s = settings
    _subnet  = subnet      or s.wg_subnet
    _allowed = allowed_ips or s.wg_allowed_ips
    _dns     = dns         or s.wg_dns
    _host    = host        or s.wg_host or "<your-server-ip>"
    _port    = port        or s.wg_port
    _secret  = peer_secret or s.wg_peer_secret.get_secret_value()

    priv, _ = _keypair(peer_id, _secret)
    ip = client_ip(peer_index, _subnet)

    return (
        "[Interface]\n"
        f"PrivateKey = {priv}\n"
        f"Address = {ip}/32\n"
        f"DNS = {_dns}\n"
        "\n"
        "[Peer]\n"
        f"PublicKey = {server_pubkey}\n"
        f"AllowedIPs = {_allowed}\n"
        f"Endpoint = {_host}:{_port}\n"
        "PersistentKeepalive = 25\n"
    )


def peer_public_key(peer_id: str, peer_secret: str | None = None) -> str:
    """Return the WireGuard public key for peer_id (for server-side peer registration)."""
    _secret = peer_secret or settings.wg_peer_secret.get_secret_value()
    _, pub = _keypair(peer_id, _secret)
    return pub
