# Node auth and handshake

This document describes the first safe integration slice from the uploaded workspace: standalone inter-node authentication primitives and peer key handshake.

## Files

- `swarm/network/auth.py` — `NodeKeys`, `AuthSigner`, `AuthVerifier`, and `make_auth_pair`.
- `swarm/network/handshake.py` — `PeerKeyRegistry`, `PeerInfo`, and `HandshakeManager`.
- `tests/test_auth.py` — unit tests for open, HMAC, replay, and Ed25519 modes.
- `tests/test_handshake.py` — unit tests for peer key registry and handshake message validation.

## Auth modes

### Open mode

```yaml
auth:
  enabled: false
```

No auth is required. This is useful only for local development.

### HMAC mode

```yaml
auth:
  enabled: true
  shared_secret: "my-swarm-secret"
  require_ed25519: false
  generate_keys: false
```

Every envelope gets a timestamp, nonce, and HMAC-SHA256 over a stable JSON body.

### Ed25519 mode

```yaml
auth:
  enabled: true
  require_ed25519: true
  generate_keys: true
  key_dir: ".swarm_keys"
```

Each node generates or loads an Ed25519 keypair. The node id is derived as the first 16 hex characters of `sha256(public_key)`.

## Replay protection

`AuthVerifier` rejects messages when:

- the timestamp is outside `MAX_CLOCK_SKEW_SEC`;
- the nonce has already been seen during the TTL window;
- HMAC validation fails when a shared secret is configured;
- Ed25519 validation fails when required.

## Handshake flow

```text
A -> B: handshake_hello {node_id, pubkey, timestamp, sig}
B -> A: ack             {ok, node_id, pubkey, timestamp, sig}
A -> B: handshake_done  {node_id, timestamp, sig}
```

After `handshake_done`, the receiving node registers the initiator in `PeerKeyRegistry`. This PR does not yet wire the primitives into `RPCServer`, `GossipProtocol`, or runtime startup; that belongs in a later integration PR.

## Test command

```bash
python -m pytest -q tests/test_auth.py tests/test_handshake.py
```
