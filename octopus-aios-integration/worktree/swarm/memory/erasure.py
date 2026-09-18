from __future__ import annotations

import logging

from reedsolo import RSCodec

logger = logging.getLogger(__name__)


class ErasureCoder:
    """Stripe-based Reed-Solomon erasure coding.

    Encodes data into data_shards + parity_shards total shards.
    Any data_shards out of total can reconstruct the original data.

    Uses per-byte striping: each byte position across shards forms
    an independent RS codeword, so losing up to parity_shards whole
    shards is tolerable.
    """

    def __init__(self, data_shards: int = 4, parity_shards: int = 2) -> None:
        self.data_shards = data_shards
        self.parity_shards = parity_shards
        self.total_shards = data_shards + parity_shards
        self._codec = RSCodec(parity_shards)

    def encode(self, data: bytes) -> list[bytes]:
        if not data:
            raise ValueError("Cannot encode empty data")

        pad_len = (self.data_shards - len(data) % self.data_shards) % self.data_shards
        padded = data + b"\x00" * pad_len
        shard_size = len(padded) // self.data_shards

        data_chunks = [
            padded[i * shard_size : (i + 1) * shard_size]
            for i in range(self.data_shards)
        ]

        parity_chunks = [bytearray() for _ in range(self.parity_shards)]
        for byte_idx in range(shard_size):
            stripe = bytes(chunk[byte_idx] for chunk in data_chunks)
            encoded = bytes(self._codec.encode(stripe))
            parity_bytes = encoded[self.data_shards :]
            for p in range(self.parity_shards):
                parity_chunks[p].append(parity_bytes[p])

        return [bytes(c) for c in data_chunks] + [bytes(p) for p in parity_chunks]

    def decode(self, shard_map: dict[int, bytes], original_length: int) -> bytes:
        if len(shard_map) < self.data_shards:
            raise ValueError(
                f"Need at least {self.data_shards} shards, got {len(shard_map)}"
            )

        shard_size = max(len(s) for s in shard_map.values())
        result_shards = [bytearray(shard_size) for _ in range(self.data_shards)]

        for byte_idx in range(shard_size):
            stripe = bytearray(self.total_shards)
            erasure_pos = []
            for i in range(self.total_shards):
                if i in shard_map and byte_idx < len(shard_map[i]):
                    stripe[i] = shard_map[i][byte_idx]
                else:
                    erasure_pos.append(i)

            decoded = self._codec.decode(bytes(stripe), erase_pos=erasure_pos)
            data_bytes = bytes(decoded[0])
            for i in range(self.data_shards):
                result_shards[i][byte_idx] = data_bytes[i]

        return b"".join(bytes(s) for s in result_shards)[:original_length]
