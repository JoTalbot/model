from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

MAX_CLOCK_SKEW_SEC = 30
HANDSHAKE_TIMEOUT  = 15.0


@dataclass
class PeerInfo:
    node_id:    str
    pubkey_hex: str
    address:    str          # "host:port"
    verified_at: float = field(default_factory=time.time)


class PeerKeyRegistry:
    def __init__(self, dsn: str | None = None) -> None:
        self._peers: dict[str, PeerInfo] = {}
        self._dsn = dsn
        if self._dsn:
            self._init_db()
            self._load_from_db()

    def _init_db(self):
        try:
            import psycopg2
            conn = psycopg2.connect(self._dsn)
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS node_registry (
                        node_id     TEXT PRIMARY KEY,
                        pubkey_hex  TEXT NOT NULL,
                        address     TEXT,
                        verified_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                    );
                """)
            conn.commit(); conn.close()
        except Exception as e:
            logger.error("Failed to init node_registry table: %s", e)

    def _load_from_db(self):
        try:
            import psycopg2
            conn = psycopg2.connect(self._dsn)
            with conn.cursor() as cur:
                cur.execute("SELECT node_id, pubkey_hex, address, EXTRACT(EPOCH FROM verified_at) FROM node_registry")
                rows = cur.fetchall()
                for nid, pk, addr, ts in rows:
                    self._peers[nid] = PeerInfo(node_id=nid, pubkey_hex=pk, address=addr or "", verified_at=ts)
            conn.close()
            logger.info("Loaded %d peers from DB registry", len(self._peers))
        except Exception as e:
            logger.error("Failed to load peers from DB: %s", e)

    def register(self, node_id: str, pubkey_hex: str, address: str = "") -> None:
        self._peers[node_id] = PeerInfo(node_id=node_id, pubkey_hex=pubkey_hex, address=address)
        if self._dsn:
            try:
                import psycopg2
                conn = psycopg2.connect(self._dsn)
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO node_registry (node_id, pubkey_hex, address, verified_at)
                        VALUES (%s, %s, %s, NOW())
                        ON CONFLICT (node_id) DO UPDATE SET
                            pubkey_hex = EXCLUDED.pubkey_hex,
                            address = EXCLUDED.address,
                            verified_at = NOW()
                    """, (node_id, pubkey_hex, address))
                conn.commit(); conn.close()
            except Exception as e:
                logger.error("Failed to save peer to DB: %s", e)
        logger.info("PeerKeyRegistry: registered %s @ %s", node_id, address)

    def unregister(self, node_id: str) -> None:
        self._peers.pop(node_id, None)
        if self._dsn:
            try:
                import psycopg2
                conn = psycopg2.connect(self._dsn)
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM node_registry WHERE node_id = %s", (node_id,))
                conn.commit(); conn.close()
            except: pass

    def get(self, node_id: str) -> PeerInfo | None:
        return self._peers.get(node_id)

    def lookup_by_pubkey(self, pubkey_hex: str) -> str | None:
        pk = pubkey_hex.lower()
        for nid, peer in self._peers.items():
            if peer.pubkey_hex.lower() == pk:
                return nid
        return None

    def all_peers(self) -> list[PeerInfo]:
        return list(self._peers.values())

    def __len__(self) -> int: return len(self._peers)
    def __contains__(self, node_id: str) -> bool: return node_id in self._peers


def _sign_payload(keys, payload: dict) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return keys.sign(body).hex()

def _verify_payload(pubkey_hex: str, payload: dict, sig_hex: str) -> bool:
    try:
        import json

        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(pubkey_hex))
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        pub.verify(bytes.fromhex(sig_hex), body)
        return True
    except: return False

def _check_timestamp(ts: float) -> bool:
    return abs(time.time() - ts) <= MAX_CLOCK_SKEW_SEC

class HandshakeManager:
    def __init__(self, node_keys, registry: PeerKeyRegistry, *, require_ed25519: bool = False) -> None:
        self._keys = node_keys
        self._registry = registry
        self._require_ed25519 = require_ed25519
        self._pending: dict[str, asyncio.Event] = {}

    def register_rpc_handlers(self, rpc_server) -> None:
        rpc_server.register("handshake_hello", self._handle_hello)
        rpc_server.register("handshake_ack",   self._handle_ack)
        rpc_server.register("handshake_done",  self._handle_done)

    async def initiate(self, rpc_client, peer_host, peer_rpc_port, peer_node_id="", expected_pubkey="", own_rpc_port=0, peer_host_self="") -> bool:
        ts = time.time()
        hello_payload = {"node_id": self._keys.node_id, "pubkey": self._keys.public_key_hex(), "timestamp": ts, "address": f"{peer_host_self or '127.0.0.1'}:{own_rpc_port}"}
        if self._keys._private_key:
            hello_payload["sig"] = _sign_payload(self._keys, hello_payload)
        try:
            resp = await asyncio.wait_for(rpc_client.call(peer_host, peer_rpc_port, "handshake_hello", hello_payload), timeout=HANDSHAKE_TIMEOUT)
            if not resp or not resp.get("ok"): return False
            peer_id, peer_pub, peer_ts, peer_sig = resp.get("node_id"), resp.get("pubkey"), resp.get("timestamp", 0), resp.get("sig", "")
            if not _check_timestamp(peer_ts): return False
            if expected_pubkey and peer_pub.lower() != expected_pubkey.lower(): return False
            if self._require_ed25519 and peer_pub and peer_sig:
                if not _verify_payload(peer_pub, {"node_id": peer_id, "pubkey": peer_pub, "timestamp": peer_ts}, peer_sig): return False
            self._registry.register(peer_id or peer_node_id, peer_pub, f"{peer_host}:{peer_rpc_port}")
            done_payload = {"node_id": self._keys.node_id, "timestamp": time.time()}
            if self._keys._private_key: done_payload["sig"] = _sign_payload(self._keys, done_payload)
            await rpc_client.call(peer_host, peer_rpc_port, "handshake_done", done_payload)
            logger.info("✅ Handshake complete: %s", peer_id)
            return True
        except: return False

    async def _handle_hello(self, params):
        nid, pub, ts, sig = params.get("node_id"), params.get("pubkey"), params.get("timestamp", 0), params.get("sig", "")
        if not _check_timestamp(ts): return {"ok": False, "reason": "clock_skew"}
        if self._require_ed25519 and pub and sig:
            if not _verify_payload(pub, {"node_id": nid, "pubkey": pub, "timestamp": ts, "address": params.get("address", "")}, sig):
                return {"ok": False, "reason": "invalid_sig"}
        self._registry.register(nid, pub, params.get("address", ""))
        self._pending[nid] = asyncio.Event()
        ack = {"ok": True, "node_id": self._keys.node_id, "pubkey": self._keys.public_key_hex(), "timestamp": time.time()}
        if self._keys._private_key: ack["sig"] = _sign_payload(self._keys, {"node_id": ack["node_id"], "pubkey": ack["pubkey"], "timestamp": ack["timestamp"]})
        return ack

    async def _handle_ack(self, p): return {"ok": True}
    async def _handle_done(self, params):
        nid, ts, sig = params.get("node_id"), params.get("timestamp", 0), params.get("sig", "")
        if not _check_timestamp(ts) or nid not in self._pending:
            return {"ok": False, "reason": "no_hello" if nid not in self._pending else "clock_skew"}
        pinfo = self._registry.get(nid)
        if self._require_ed25519 and pinfo and sig:
            if not _verify_payload(pinfo.pubkey_hex, {"node_id": nid, "timestamp": ts}, sig): return {"ok": False}
        self._pending.pop(nid).set()
        return {"ok": True}

    def stats(self): return {"known_peers": len(self._registry), "require_ed25519": self._require_ed25519, "pending_shakes": len(self._pending)}
