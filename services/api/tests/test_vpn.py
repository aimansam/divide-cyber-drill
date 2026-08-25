"""Tests for WireGuard VPN service + GET /api/v1/auth/vpn-config endpoint."""
from __future__ import annotations
import base64
import pytest
from fastapi.testclient import TestClient
from app.services.vpn import (
    _clamp, _keypair, assign_peer_id, build_client_config,
    client_ip, peer_public_key, server_ip,
)

_SECRET = "test-secret-32-chars-minimum-aaaa"


class TestClamp:
    def test_32_bytes(self):
        assert len(_clamp(b"\xff" * 32)) == 32
    def test_low3_byte0_cleared(self):
        assert _clamp(b"\x07" + b"\x00" * 31)[0] & 0b111 == 0
    def test_highbit_byte31_cleared(self):
        assert _clamp(b"\x00" * 31 + b"\xff")[31] & 0x80 == 0
    def test_secondhigh_byte31_set(self):
        assert _clamp(b"\x00" * 32)[31] & 0x40 != 0


class TestKeypair:
    def test_priv_32b(self):
        priv, _ = _keypair("p1", _SECRET)
        assert len(base64.b64decode(priv)) == 32
    def test_pub_32b(self):
        _, pub = _keypair("p1", _SECRET)
        assert len(base64.b64decode(pub)) == 32
    def test_stable(self):
        assert _keypair("stable", _SECRET) == _keypair("stable", _SECRET)
    def test_different_ids(self):
        assert _keypair("a", _SECRET) != _keypair("b", _SECRET)
    def test_different_secret(self):
        assert _keypair("x", "aaa" * 11) != _keypair("x", "bbb" * 11)


class TestIpAllocation:
    def test_server_ip(self):
        assert server_ip("10.13.37.0/24") == "10.13.37.1"
    def test_client_1(self):
        assert client_ip(1, "10.13.37.0/24") == "10.13.37.2"
    def test_client_2(self):
        assert client_ip(2, "10.13.37.0/24") == "10.13.37.3"
    def test_exhausted(self):
        with pytest.raises(ValueError, match="exhausted"):
            client_ip(300, "10.13.37.0/24")


class TestBuildConfig:
    def _conf(self, idx: int = 1) -> str:
        return build_client_config(
            peer_id="test-peer", peer_index=idx,
            server_pubkey="FAKE" + "A" * 39 + "=",
            subnet="10.13.37.0/24", allowed_ips="10.10.0.0/16",
            dns="1.1.1.1", host="203.0.113.1", port=51820,
            peer_secret=_SECRET,
        )

    def test_interface(self): assert "[Interface]" in self._conf()
    def test_peer(self): assert "[Peer]" in self._conf()
    def test_addr_idx1(self): assert "Address = 10.13.37.2/32" in self._conf(1)
    def test_addr_idx2(self): assert "Address = 10.13.37.3/32" in self._conf(2)
    def test_endpoint(self): assert "Endpoint = 203.0.113.1:51820" in self._conf()
    def test_allowed(self): assert "AllowedIPs = 10.10.0.0/16" in self._conf()
    def test_dns(self): assert "DNS = 1.1.1.1" in self._conf()
    def test_keepalive(self): assert "PersistentKeepalive = 25" in self._conf()

    def test_privkey_valid_b64(self):
        for line in self._conf().splitlines():
            if line.startswith("PrivateKey"):
                val = line.split("=", 1)[1].strip()
                assert len(base64.b64decode(val)) == 32


class TestPeerPublicKey:
    def test_valid_b64(self):
        assert len(base64.b64decode(peer_public_key("p1", _SECRET))) == 32
    def test_stable(self):
        assert peer_public_key("p2", _SECRET) == peer_public_key("p2", _SECRET)


class TestVpnConfigEndpoint:
    """Tests for GET /api/v1/auth/vpn-config.

    Uses the setup endpoint to create the first admin, then creates
    additional users via POST /auth/users (admin-only endpoint).
    """

    def _setup_admin(self, client: TestClient, sub: str = "vpn-setup-admin") -> str:
        """Create first admin via /auth/setup, return token."""
        r = client.post("/api/v1/auth/setup", json={"sub": sub, "password": "adminpw1234"})
        # 201 on first call; 409 if already created in another test (DB shared).
        if r.status_code == 201:
            return r.json()["token"]
        # Already exists — log in instead.
        lr = client.post("/api/v1/auth/login", json={"sub": sub, "password": "adminpw1234"})
        return lr.json()["token"]

    def _create_user(self, client: TestClient, admin_tok: str, sub: str, pw: str) -> str:
        """Admin creates a user, returns their login token."""
        client.post(
            "/api/v1/auth/users",
            json={"sub": sub, "password": pw, "role": "red"},
            headers={"X-Divide-Token": admin_tok},
        )
        lr = client.post("/api/v1/auth/login", json={"sub": sub, "password": pw})
        return lr.json()["token"]

    def test_200_for_auth_user(self, client: TestClient):
        tok = self._setup_admin(client)
        r = client.get("/api/v1/auth/vpn-config", headers={"X-Divide-Token": tok})
        assert r.status_code == 200

    def test_config_has_sections(self, client: TestClient):
        admin_tok = self._setup_admin(client)
        tok = self._create_user(client, admin_tok, "vpn-u1", "pass12345678")
        d = client.get("/api/v1/auth/vpn-config", headers={"X-Divide-Token": tok}).json()
        assert "[Interface]" in d["config"] and "[Peer]" in d["config"]

    def test_stable_on_repeat(self, client: TestClient):
        admin_tok = self._setup_admin(client)
        tok = self._create_user(client, admin_tok, "vpn-u2", "pass12345678")
        h = {"X-Divide-Token": tok}
        r1 = client.get("/api/v1/auth/vpn-config", headers=h).json()
        r2 = client.get("/api/v1/auth/vpn-config", headers=h).json()
        assert r1["config"] == r2["config"]
        assert r1["client_ip"] == r2["client_ip"]

    def test_401_without_token(self, client: TestClient):
        assert client.get("/api/v1/auth/vpn-config").status_code == 401

    def test_filename_has_sub(self, client: TestClient):
        admin_tok = self._setup_admin(client)
        tok = self._create_user(client, admin_tok, "vpn-alice2", "pass12345678")
        d = client.get("/api/v1/auth/vpn-config", headers={"X-Divide-Token": tok}).json()
        assert "vpn-alice2" in d["filename"] and d["filename"].endswith(".conf")

    def test_all_fields_present(self, client: TestClient):
        admin_tok = self._setup_admin(client)
        tok = self._create_user(client, admin_tok, "vpn-bob2", "pass12345678")
        d = client.get("/api/v1/auth/vpn-config", headers={"X-Divide-Token": tok}).json()
        for f in ("config", "filename", "client_ip", "server_ip", "allowed_ips"):
            assert f in d, f"missing: {f}"
