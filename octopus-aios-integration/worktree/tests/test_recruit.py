"""
tests/test_recruit.py
──────────────────────
Тесты Gossip-рекрутинга.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import io
import time
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarm.recruit.recruiter import (
    MAX_CHILDREN,
    RECRUIT_COOLDOWN_SEC,
    RecruitHandler,
    Recruiter,
    SourcePacker,
)


# ════════════════════════════════════════════════════════════════════════════
# SourcePacker
# ════════════════════════════════════════════════════════════════════════════

def test_packer_produces_zip(tmp_path):
    """Упаковщик должен создать валидный zip."""
    (tmp_path / "node.py").write_text("# entry\n")
    (tmp_path / "swarm").mkdir()
    (tmp_path / "swarm" / "module.py").write_text("# module\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "cached.pyc").write_bytes(b"\x00\x01")

    packer = SourcePacker(tmp_path)
    data, digest = packer.pack()

    assert len(data) > 0
    assert len(digest) == 64   # SHA-256 hex

    # Проверяем zip
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
    assert "node.py" in names
    assert "swarm/module.py" in names
    # __pycache__ исключён
    assert not any("__pycache__" in n for n in names)
    assert not any(".pyc" in n for n in names)


def test_packer_digest_stable(tmp_path):
    """Digest должен быть стабильным для одних и тех же файлов."""
    (tmp_path / "a.py").write_text("x = 1\n")
    packer = SourcePacker(tmp_path)
    _, d1 = packer.pack()
    _, d2 = packer.pack()
    assert d1 == d2


# ════════════════════════════════════════════════════════════════════════════
# Recruiter
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def mock_gossip():
    g = MagicMock()
    g.inject = AsyncMock()
    g._peers = [("127.0.0.1", 9001)]
    return g


@pytest.fixture()
def recruiter(tmp_path, mock_gossip):
    (tmp_path / "node.py").write_text("# entry\n")
    packer = SourcePacker(tmp_path)
    r = Recruiter(
        node_id="recruiter-1",
        host="127.0.0.1",
        rpc_port=10000,
        gossip=mock_gossip,
        secret="test-secret",
        interval=1.0,
        packer=packer,
    )
    r._pack_archive()
    return r


def test_recruiter_token_format(recruiter):
    """Токен должен быть 64-символьным hex."""
    assert len(recruiter._token) == 64
    int(recruiter._token, 16)   # должен быть hex


def test_recruiter_token_depends_on_digest(recruiter):
    """Разные digest → разные токены."""
    t1 = recruiter._token
    recruiter._digest = "fakedigest"
    recruiter._token  = recruiter._make_token()
    assert t1 != recruiter._token


@pytest.mark.asyncio
async def test_recruiter_fetch_valid_token(recruiter):
    """Валидный токен → архив возвращается."""
    res = await recruiter._handle_fetch({"token": recruiter._token, "peer_id": "p1"})
    assert res["ok"]
    assert isinstance(res["data"], list)
    assert len(res["data"]) > 0
    assert res["digest"] == recruiter._digest


@pytest.mark.asyncio
async def test_recruiter_fetch_invalid_token(recruiter):
    """Неверный токен → отказ."""
    res = await recruiter._handle_fetch({"token": "wrongtoken", "peer_id": "p1"})
    assert not res["ok"]
    assert res["reason"] == "invalid_token"


@pytest.mark.asyncio
async def test_recruiter_fetch_open_mode(tmp_path, mock_gossip):
    """Без секрета — токен не проверяется."""
    (tmp_path / "node.py").write_text("# entry\n")
    packer = SourcePacker(tmp_path)
    r = Recruiter(
        node_id="r", host="127.0.0.1", rpc_port=10000,
        gossip=mock_gossip, secret="", packer=packer,
    )
    r._pack_archive()
    res = await r._handle_fetch({"token": "anything", "peer_id": "p"})
    assert res["ok"]


# ════════════════════════════════════════════════════════════════════════════
# RecruitHandler
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def mock_rpc_client():
    client = MagicMock()
    client.call = AsyncMock()
    return client


@pytest.fixture()
def handler(tmp_path, mock_rpc_client):
    return RecruitHandler(
        node_id="candidate-1",
        rpc_client=mock_rpc_client,
        secret="test-secret",
        base_port=8100,
        max_children=2,
        spawn_interval=0,    # без cooldown в тестах
        spawn_dir=tmp_path / "nodes",
        enabled=True,
    )


@pytest.mark.asyncio
async def test_handler_ignores_self_recruit(handler):
    """Нода не должна рекрутировать саму себя."""
    from swarm.network.gossip import GossipMessage
    msg = GossipMessage(
        msg_type="RECRUIT",
        payload={
            "recruiter_id": "candidate-1",   # тот же node_id
            "rpc_host": "127.0.0.1",
            "rpc_port": 10000,
            "token": "",
            "digest": "",
            "ts": time.time(),
        }
    )
    # Не должно падать и не должно ничего делать
    await handler.handle_gossip(msg)
    handler.rpc_client.call.assert_not_called()


@pytest.mark.asyncio
async def test_handler_disabled(handler):
    """Отключённый handler игнорирует RECRUIT."""
    from swarm.network.gossip import GossipMessage
    handler.enabled = False
    msg = GossipMessage(msg_type="RECRUIT", payload={
        "recruiter_id": "other", "rpc_host": "h", "rpc_port": 1,
        "token": "", "digest": "", "ts": time.time(),
    })
    await handler.handle_gossip(msg)
    handler.rpc_client.call.assert_not_called()


@pytest.mark.asyncio
async def test_handler_invalid_token(handler):
    """Неверный HMAC-токен → не скачиваем архив."""
    from swarm.network.gossip import GossipMessage
    msg = GossipMessage(msg_type="RECRUIT", payload={
        "recruiter_id": "other-node",
        "rpc_host": "127.0.0.1",
        "rpc_port": 10000,
        "token": "badtoken",
        "digest": "fakedigest",
        "ts": time.time(),
    })
    await handler.handle_gossip(msg)
    handler.rpc_client.call.assert_not_called()


@pytest.mark.asyncio
async def test_handler_cooldown(handler):
    """Второй RECRUIT от того же вербовщика в пределах cooldown — игнорируется."""
    from swarm.network.gossip import GossipMessage
    handler._seen_recruiters["r1"] = time.time()   # уже видели только что

    msg = GossipMessage(msg_type="RECRUIT", payload={
        "recruiter_id": "r1", "rpc_host": "h", "rpc_port": 1,
        "token": "", "digest": "", "ts": time.time(),
    })
    await handler.handle_gossip(msg)
    handler.rpc_client.call.assert_not_called()


@pytest.mark.asyncio
async def test_handler_max_children(handler, tmp_path):
    """Лимит дочерних нод — не спавним больше max_children."""
    # Симулируем уже запущенные процессы
    handler._children = [MagicMock(poll=MagicMock(return_value=None))] * 2

    from swarm.network.gossip import GossipMessage
    msg = GossipMessage(msg_type="RECRUIT", payload={
        "recruiter_id": "r2", "rpc_host": "h", "rpc_port": 1,
        "token": "", "digest": "", "ts": time.time(),
    })
    # Нет секрета — обходим проверку токена
    handler._secret = b""
    await handler.handle_gossip(msg)
    handler.rpc_client.call.assert_not_called()


def test_handler_unpack_path_traversal(handler, tmp_path):
    """Path traversal в архиве → ValueError."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.py", "import os; os.system('rm -rf /')")
    data = buf.getvalue()

    dest = tmp_path / "dest"
    with pytest.raises((ValueError, Exception)):
        handler._unpack(data, dest)


def test_handler_stats(handler):
    s = handler.stats()
    assert "active_children" in s
    assert "max_children"    in s
    assert "enabled"         in s


# ════════════════════════════════════════════════════════════════════════════
# Recruiter stats
# ════════════════════════════════════════════════════════════════════════════

def test_recruiter_stats(recruiter):
    s = recruiter.stats()
    assert "recruited"    in s
    assert "archive_size" in s
    assert s["archive_size"] > 0
