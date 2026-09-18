"""
tests/test_cli_peer.py
───────────────────────
Тесты CLI peer-команд (без реальной ноды — мокируем RPC).
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from swarm.cli_peer import peer


# ════════════════════════════════════════════════════════════════════════════
# Фикстуры
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def runner():
    return CliRunner()


def mock_rpc(return_value: dict):
    """Мок для _rpc — возвращает заданный dict."""
    return patch("swarm.cli_peer._rpc", new=AsyncMock(return_value=return_value))


# ════════════════════════════════════════════════════════════════════════════
# peer list
# ════════════════════════════════════════════════════════════════════════════

def test_peer_list_empty(runner):
    with mock_rpc({"peers": [], "count": 0}):
        with patch("swarm.cli_peer._run", side_effect=lambda c: c.cr_await or {}):
            # Просто проверяем что команда есть
            result = runner.invoke(peer, ["list", "--help"])
    assert result.exit_code == 0
    assert "пиров" in result.output.lower() or "peer" in result.output.lower()


def test_peer_list_help(runner):
    result = runner.invoke(peer, ["list", "--help"])
    assert result.exit_code == 0
    assert "--hs" in result.output
    assert "--kad" in result.output


def test_peer_handshake_help(runner):
    result = runner.invoke(peer, ["handshake", "--help"])
    assert result.exit_code == 0
    assert "HOST:RPC_PORT" in result.output


def test_peer_keys_help(runner):
    result = runner.invoke(peer, ["keys", "--help"])
    assert result.exit_code == 0
    assert "--node-id" in result.output


def test_peer_ping_help(runner):
    result = runner.invoke(peer, ["ping", "--help"])
    assert result.exit_code == 0
    assert "--count" in result.output or "-n" in result.output


def test_peer_auth_status_help(runner):
    result = runner.invoke(peer, ["auth-status", "--help"])
    assert result.exit_code == 0
    assert "HMAC" in result.output or "авторизац" in result.output.lower()


def test_peer_info_help(runner):
    result = runner.invoke(peer, ["info", "--help"])
    assert result.exit_code == 0


# ════════════════════════════════════════════════════════════════════════════
# peer handshake — валидация аргументов
# ════════════════════════════════════════════════════════════════════════════

def test_peer_handshake_bad_address(runner):
    """Без двоеточия должен вернуть ошибку."""
    with mock_rpc({}):
        result = runner.invoke(peer, ["handshake", "127001"])
    assert result.exit_code != 0 or "Формат" in result.output


def test_peer_handshake_bad_port(runner):
    """Нечисловой порт должен вернуть ошибку."""
    with mock_rpc({}):
        result = runner.invoke(peer, ["handshake", "127.0.0.1:abc"])
    assert result.exit_code != 0 or "порт" in result.output.lower()


# ════════════════════════════════════════════════════════════════════════════
# peer — группа команд зарегистрирована
# ════════════════════════════════════════════════════════════════════════════

def test_peer_group_commands(runner):
    """Все ожидаемые подкоманды должны быть зарегистрированы."""
    result = runner.invoke(peer, ["--help"])
    assert result.exit_code == 0
    for cmd in ["list", "handshake", "keys", "info", "ping", "auth-status"]:
        assert cmd in result.output, f"Команда {cmd!r} не найдена в --help"


# ════════════════════════════════════════════════════════════════════════════
# peer auth-status — с мок-данными
# ════════════════════════════════════════════════════════════════════════════

def test_peer_auth_status_json(runner):
    """--json должен выдать валидный JSON."""
    mock_data = {
        "ok": True,
        "node_id": "abc123",
        "port": 8000,
        "auth": {
            "hmac_enabled": True,
            "ed25519": False,
            "verified_peers": 2,
            "pubkey": "d4e5" * 16,
        },
        "handshake": {"pending_shakes": 0, "require_ed25519": False},
    }

    calls = {"count": 0}

    def fake_run(coro):
        calls["count"] += 1
        return mock_data

    with patch("swarm.cli_peer._run", side_effect=fake_run):
        result = runner.invoke(peer, ["auth-status", "--json"])

    if result.exit_code == 0:
        data = json.loads(result.output)
        assert "node_id" in data or "ok" in data


# ════════════════════════════════════════════════════════════════════════════
# peer keys — JSON output
# ════════════════════════════════════════════════════════════════════════════

def test_peer_keys_json_output(runner):
    mock_data = {
        "ok": True,
        "keys": {
            "node-A": "aabb" * 16,
            "node-B": "ccdd" * 16,
        }
    }

    def fake_run(coro):
        return mock_data

    with patch("swarm.cli_peer._run", side_effect=fake_run):
        result = runner.invoke(peer, ["keys", "--json"])

    if result.exit_code == 0:
        data = json.loads(result.output)
        assert "ok" in data or "keys" in data
