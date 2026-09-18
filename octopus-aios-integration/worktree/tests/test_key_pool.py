import time

import pytest

from swarm.llm.key_pool import APIKey, KeyPool


def test_get_key_round_robin():
    pool = KeyPool(keys=[APIKey(key="k1"), APIKey(key="k2"), APIKey(key="k3")])
    keys = [pool.get_key().key for _ in range(6)]
    assert keys == ["k1", "k2", "k3", "k1", "k2", "k3"]


def test_get_key_skips_cooldown():
    pool = KeyPool(keys=[APIKey(key="k1"), APIKey(key="k2")])
    pool.mark_failed(pool.keys[0], cooldown_seconds=60)
    keys = [pool.get_key().key for _ in range(3)]
    assert keys == ["k2", "k2", "k2"]


def test_get_key_raises_when_all_in_cooldown():
    pool = KeyPool(keys=[APIKey(key="k1")])
    pool.mark_failed(pool.keys[0], cooldown_seconds=60)
    with pytest.raises(RuntimeError, match="No available API keys"):
        pool.get_key()


def test_mark_success_resets_error():
    pool = KeyPool(keys=[APIKey(key="k1")])
    pool.mark_failed(pool.keys[0], cooldown_seconds=0)
    pool.mark_success(pool.keys[0])
    assert pool.keys[0].last_error is None
    assert pool.keys[0].cooldown_until is None


def test_cooldown_expires():
    pool = KeyPool(keys=[APIKey(key="k1")])
    pool.keys[0].cooldown_until = time.time() - 1
    key = pool.get_key()
    assert key.key == "k1"


def test_empty_pool_raises():
    with pytest.raises(ValueError, match="At least one API key"):
        KeyPool(keys=[])
