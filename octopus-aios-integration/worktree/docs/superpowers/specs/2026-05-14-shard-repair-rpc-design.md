# Shard Repair API (RPC pull) — Design Spec

## Goals

- Improve fault tolerance when some shard keys are missing in the DHT view of a node.
- Speed up recovery versus the previous `repair_shards_once` that only called `retrieve` and logged.
- Reduce load on a single owner by pulling missing shards from peers that still hold them.

## Architecture

```text
repair_shards_once(block_id)
  → load meta; enumerate missing shard indices locally
  → for each missing index (bounded parallelism): RPC memory_shard_get on
     replica_hints → repair_seeds (kad→rpc port) → Kademlia neighbors (kad→rpc)
  → build tentative shard map; decode(content_length); on success re-encode
     and write only previously-missing indices back via kademlia.set
  → retrieve(block_id) must succeed to return True
```

## RPC: `memory_shard_get`

- **Params:** `block_id: str`, `shard_index: int`.
- **Result:** `{ "ok": bool, "shard": bytes | null, "error": str | null }`.
- **Behaviour:** Handler reads `shard:{block_id}:{shard_index}` from the same local Kademlia/storage as `DistributedMemory.store`. Returns `shard: null` if absent.

## Meta: `replica_hints`

- Optional msgpack field on `meta:<block_id>`: `replica_hints: list[{ "node_id": str, "rpc_host": str, "rpc_port": int }]`.
- On `store`, the writing node appends its own endpoint when `ShardRepairSettings.local_rpc_host` and `local_rpc_port` are set (in `node.py`: `node.advertise_host` and `kad_port + repair_rpc_port_offset`).
- Older blocks without the field use only seed list + neighbour scan.

## Repair algorithm

1. If `retrieve` succeeds, return `True`.
2. Load `meta:`; if missing, return `False`.
3. Build `shard_map` from local `get`; `missing` = indices with no bytes.
4. For each index in `missing`, fetch bytes (semaphore limits concurrent indices):
   - **Phase A:** each unique `(rpc_host, rpc_port)` from `replica_hints` (order preserved), timeout per RPC.
   - **Phase B:** `repair_seeds` from config (`host:kad_port` → RPC port = kad + offset), then `get_peers()` strings parsed as `host:kad` with same offset.
   - Stop each index after first successful non-empty bytes or after `repair_max_peers_per_shard` distinct endpoints tried per shard.
5. Merge into `tentative`; if `len(tentative) < data_shards`, return `False`.
6. `decode(tentative, content_length)` inside try/except; on failure log and return `False` without writing.
7. On success: `encode(content)` and `set` only indices that were in `missing`.

## Security (v1)

- Same trust model as existing open RPC (LAN / trusted network); no signatures.
- Malicious or corrupt shards must not be persisted unless `decode` succeeds; failed decode discards the round’s writes.

## Configuration (`config.yaml` under `memory`)

- `repair_rpc_timeout_seconds` (default `8`)
- `repair_max_peers_per_shard` (default `32`)
- `repair_parallel_fetches` (default `3`)
- `repair_rpc_port_offset` (default `2000`, i.e. RPC = Kademlia + 2000 as in `node.py`)
- `repair_seeds`: list of strings `host:kad_port` for bootstrap peers during repair

## Testing

- Unit tests with mocked `RPCClient` and in-memory Kademlia: missing shard filled via RPC, then `retrieve` succeeds.
- Negative: corrupt remote payload leading to decode failure leaves storage without new keys for that round.
- Multi-peer: first RPC endpoint returns empty `shard` bytes; repair succeeds via the second seed (`test_repair_tries_second_rpc_peer_when_first_returns_empty`).

## Non-goals (v1)

- Gossip-based “who has shard X” discovery (optional later).
- Authenticated or encrypted shard transfer.
