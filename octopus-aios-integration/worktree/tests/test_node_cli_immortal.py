"""Smoke tests for the new immortal-memory CLI commands.

Each test invokes the Click command directly with isolated tmp paths,
so the suite stays fully offline.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from click.testing import CliRunner

from node import cli


def _write_cfg(tmp_path: Path, *, obsidian: bool = False) -> Path:
    cfg = {
        "memory_facade": {
            "enabled": True,
            "scratch_root": str(tmp_path / "scratch"),
        }
    }
    if obsidian:
        cfg["memory_facade"]["obsidian"] = {
            "enabled": True,
            "vault_root": str(tmp_path / "vault"),
        }
    tmp_path.mkdir(parents=True, exist_ok=True)
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return p


def test_cli_memory_metrics_empty(tmp_path: Path):
    cfg = _write_cfg(tmp_path)
    r = CliRunner().invoke(cli, ["memory", "metrics", "--config", str(cfg), "--json"])
    assert r.exit_code == 0, r.output
    assert r.output.strip().startswith("{")
    assert json.loads(r.output) == {}


def test_cli_memory_wiki_then_query_and_graph(tmp_path: Path):
    cfg = _write_cfg(tmp_path, obsidian=True)

    body_file = tmp_path / "page.md"
    body_file.write_text("see [[Other]]", encoding="utf-8")
    r = CliRunner().invoke(
        cli,
        [
            "memory", "wiki",
            "--title", "Alpha",
            "--body", f"@{body_file}",
            "--tag", "kb",
            "--config", str(cfg),
        ],
    )
    assert r.exit_code == 0, r.output
    assert r.output.strip().startswith("ref:obsidian:alpha")

    g = CliRunner().invoke(
        cli, ["memory", "graph", "--kind", "wiki", "--format", "json", "--config", str(cfg)]
    )
    assert g.exit_code == 0, g.output
    parsed = json.loads(g.output)
    ids = {n["id"] for n in parsed["nodes"]}
    assert "alpha" in ids
    assert "other" in ids  # dangling [[Other]] -> 'missing' node


def test_cli_memory_snapshot_and_restore_repository(tmp_path: Path):
    cfg = _write_cfg(tmp_path)
    runner = CliRunner()

    # Seed a couple of rows
    r = runner.invoke(
        cli,
        [
            "memory", "insert",
            "--table", "parts",
            "--data", '{"v":1}',
            "--config", str(cfg),
        ],
    )
    assert r.exit_code == 0, r.output
    r = runner.invoke(
        cli,
        [
            "memory", "insert",
            "--table", "parts",
            "--data", '{"v":2}',
            "--config", str(cfg),
        ],
    )
    assert r.exit_code == 0, r.output

    # Dump
    snap = tmp_path / "snap.jsonl"
    r = runner.invoke(
        cli, ["memory", "snapshot", "--out", str(snap), "--kind", "repository", "--config", str(cfg)]
    )
    assert r.exit_code == 0, r.output
    assert snap.is_file()
    assert "__gemaxi_snapshot__" in snap.read_text(encoding="utf-8")

    # Restore into a brand-new scratch root
    cfg2 = _write_cfg(tmp_path / "b")
    r = runner.invoke(
        cli, ["memory", "restore", str(snap), "--kind", "repository", "--config", str(cfg2)]
    )
    assert r.exit_code == 0, r.output
    assert "restored 2 records" in r.output


def test_cli_memory_bootstrap_manifest(tmp_path: Path):
    out = tmp_path / "manifest.json"
    r = CliRunner().invoke(
        cli,
        [
            "memory", "bootstrap-manifest",
            "--out", str(out),
            "--seed", "10.0.0.1:8000",
            "--seed", "node.example:9000:kademlia",
            "--entry", "ref:nullpointer:https://0x0.st/Ab:purpose=manifest_mirror",
            "--notes", "phone-only seed",
        ],
    )
    assert r.exit_code == 0, r.output
    assert out.is_file()
    parsed = json.loads(out.read_text(encoding="utf-8"))
    assert parsed["__gemaxi_manifest__"] is True
    assert len(parsed["seeds"]) == 2
    assert parsed["entries"][0]["purpose"] == "manifest_mirror"


def test_cli_memory_dropbox_round_trip(tmp_path: Path, monkeypatch):
    """Dropbox upload/info/download via CLI with a stubbed cloud adapter."""
    # Build a config with our fake scheme enabled via monkeypatching the port
    # builder.  We register one fake cloud adapter so the dropbox can fan out
    # without touching the real network.
    cfg_path = _write_cfg(tmp_path)

    # Patch _build_cloud_memory_port to add a fake adapter.
    import node as _node
    from swarm.memory.adapters.local_scratch import LocalScratchAdapter
    from swarm.memory.composite import CompositeMemoryPort
    from tests.test_dropbox import _FakeCloud  # reuse the fake in-memory adapter

    # Stable adapter instances so state persists across CLI invocations.
    shared_clouds = {"alpha": _FakeCloud("alpha"), "beta": _FakeCloud("beta")}

    def _fake_builder(cfg):
        scratch = (cfg.get("memory_facade") or {}).get(
            "scratch_root", ".swarm_scratch"
        )
        adapters: dict[str, object] = {"file": LocalScratchAdapter(scratch)}
        adapters.update(shared_clouds)
        return CompositeMemoryPort(adapters)

    monkeypatch.setattr(_node, "_build_cloud_memory_port", _fake_builder)

    src = tmp_path / "payload.bin"
    payload = b"dropbox smoke test " * 200
    src.write_bytes(payload)

    runner = CliRunner()
    r = runner.invoke(
        cli,
        [
            "memory", "dropbox-upload", str(src),
            "--replication", "2",
            "--chunk-size", "128",
            "--config", str(cfg_path),
        ],
    )
    assert r.exit_code == 0, r.output
    # stdout + stderr are mixed by CliRunner -- find the canonical line.
    dropbox_lines = [
        ln.strip() for ln in r.output.splitlines() if ln.strip().startswith("dropbox:")
    ]
    assert dropbox_lines, r.output
    ref = dropbox_lines[0]

    out = tmp_path / "restored.bin"
    r = runner.invoke(
        cli,
        [
            "memory", "dropbox-download", ref,
            "--out", str(out),
            "--config", str(cfg_path),
        ],
    )
    assert r.exit_code == 0, r.output
    assert out.read_bytes() == payload

    r = runner.invoke(
        cli,
        ["memory", "dropbox-info", ref, "--json", "--config", str(cfg_path)],
    )
    assert r.exit_code == 0, r.output
    parsed = json.loads(r.output)
    assert parsed["size"] == len(payload)
    assert parsed["min_replicas"] == 2


class _FailingCloud:
    scheme = "bad"

    async def put(self, artifact):
        raise RuntimeError("network should not be used when --schemes=file")

    async def get(self, ref: str):
        raise RuntimeError("network should not be used when --schemes=file")

    async def exists(self, ref: str) -> bool:
        return False

    async def delete(self, ref: str) -> bool:
        return False

    async def search(self, tags, owner):
        return []

    def capabilities(self):
        from swarm.memory.types import Capabilities

        return Capabilities(
            schemes=frozenset({self.scheme}),
            supports_search=False,
            supports_delete=False,
            supports_promote=False,
        )


def test_cli_memory_dropbox_schemes_applies_to_manifest(tmp_path: Path, monkeypatch):
    """--schemes must route both chunks and manifest, not only chunks."""
    cfg_path = _write_cfg(tmp_path)

    import node as _node
    from swarm.memory.adapters.local_scratch import LocalScratchAdapter
    from swarm.memory.composite import CompositeMemoryPort

    def _fake_builder(cfg):
        scratch = (cfg.get("memory_facade") or {}).get(
            "scratch_root", ".swarm_scratch"
        )
        return CompositeMemoryPort(
            {"file": LocalScratchAdapter(scratch), "bad": _FailingCloud()}
        )

    monkeypatch.setattr(_node, "_build_cloud_memory_port", _fake_builder)

    src = tmp_path / "local-only.txt"
    payload = b"local dropbox via cli" * 10
    src.write_bytes(payload)

    runner = CliRunner()
    r = runner.invoke(
        cli,
        [
            "memory", "dropbox-upload", str(src),
            "--schemes", "file",
            "--replication", "1",
            "--chunk-size", "16",
            "--config", str(cfg_path),
        ],
    )
    assert r.exit_code == 0, r.output
    ref = next(
        ln.strip() for ln in r.output.splitlines() if ln.strip().startswith("dropbox:")
    )
    assert ref.startswith("dropbox:ref:file:")

    out = tmp_path / "local-only.out"
    r = runner.invoke(
        cli,
        [
            "memory", "dropbox-download", ref,
            "--out", str(out),
            "--config", str(cfg_path),
        ],
    )
    assert r.exit_code == 0, r.output
    assert out.read_bytes() == payload


def test_cli_memory_zk_upload_schemes_applies_to_manifest(tmp_path: Path, monkeypatch):
    """Encrypted upload also passes --schemes through to the manifest."""
    cfg_path = _write_cfg(tmp_path)

    import node as _node
    from swarm.memory.adapters.local_scratch import LocalScratchAdapter
    from swarm.memory.composite import CompositeMemoryPort

    def _fake_builder(cfg):
        scratch = (cfg.get("memory_facade") or {}).get(
            "scratch_root", ".swarm_scratch"
        )
        return CompositeMemoryPort(
            {"file": LocalScratchAdapter(scratch), "bad": _FailingCloud()}
        )

    monkeypatch.setattr(_node, "_build_cloud_memory_port", _fake_builder)

    src = tmp_path / "secret.txt"
    payload = b"encrypted local dropbox via cli" * 10
    src.write_bytes(payload)

    runner = CliRunner()
    r = runner.invoke(
        cli,
        [
            "memory", "zk-upload", str(src),
            "--schemes", "file",
            "--replication", "1",
            "--chunk-size", "16",
            "--config", str(cfg_path),
        ],
    )
    assert r.exit_code == 0, r.output
    share = next(
        ln.strip() for ln in r.output.splitlines() if ln.strip().startswith("zk:")
    )
    assert share.startswith("zk:dropbox:ref:file:")

    out = tmp_path / "secret.out"
    r = runner.invoke(
        cli,
        [
            "memory", "zk-download", share,
            "--out", str(out),
            "--config", str(cfg_path),
        ],
    )
    assert r.exit_code == 0, r.output
    assert out.read_bytes() == payload


def test_cli_memory_vector_add_then_search(tmp_path: Path):
    cfg = _write_cfg(tmp_path)
    runner = CliRunner()
    r = runner.invoke(
        cli,
        [
            "memory", "vector-add",
            "--id", "p1",
            "--text", "автостекло lada granta замена",
            "--config", str(cfg),
        ],
    )
    assert r.exit_code == 0, r.output
    r = runner.invoke(
        cli,
        [
            "memory", "vector-add",
            "--id", "p2",
            "--text", "редуктор toyota camry",
            "--config", str(cfg),
        ],
    )
    assert r.exit_code == 0, r.output
    r = runner.invoke(
        cli,
        [
            "memory", "vector-search",
            "автостекло",
            "--top", "1",
            "--config", str(cfg),
        ],
    )
    assert r.exit_code == 0, r.output
    assert "p1" in r.output
