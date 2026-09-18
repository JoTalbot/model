import os

import pytest

from swarm.memory.erasure import ErasureCoder


@pytest.fixture
def coder():
    return ErasureCoder(data_shards=4, parity_shards=2)


def test_encode_produces_correct_shard_count(coder):
    data = b"Hello, Immortal Swarm! This is a test of erasure coding."
    shards = coder.encode(data)
    assert len(shards) == 6


def test_decode_with_all_shards(coder):
    data = b"Hello, Immortal Swarm! This is a test of erasure coding."
    shards = coder.encode(data)
    shard_map = {i: s for i, s in enumerate(shards)}
    result = coder.decode(shard_map, original_length=len(data))
    assert result == data


def test_decode_with_missing_shards(coder):
    data = b"Test data for recovery with missing shards in the swarm."
    shards = coder.encode(data)
    shard_map = {i: s for i, s in enumerate(shards) if i not in (1, 4)}
    assert len(shard_map) == 4
    result = coder.decode(shard_map, original_length=len(data))
    assert result == data


def test_decode_fails_with_too_few_shards(coder):
    data = b"Not enough shards to recover this data."
    shards = coder.encode(data)
    shard_map = {0: shards[0], 2: shards[2], 5: shards[5]}
    with pytest.raises(Exception):
        coder.decode(shard_map, original_length=len(data))


def test_encode_empty_data(coder):
    with pytest.raises(ValueError, match="Cannot encode empty data"):
        coder.encode(b"")


def test_roundtrip_large_data(coder):
    data = os.urandom(10000)
    shards = coder.encode(data)
    shard_map = {i: s for i, s in enumerate(shards)}
    result = coder.decode(shard_map, original_length=len(data))
    assert result == data
