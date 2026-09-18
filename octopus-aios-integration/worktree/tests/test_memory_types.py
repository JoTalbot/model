from swarm.memory.types import Artifact, Capabilities, RefMeta


def test_artifact_defaults():
    a = Artifact(content=b"hi")
    assert a.content == b"hi"
    assert a.mime == "application/octet-stream"
    assert a.tags == []
    assert a.provenance == {}
    assert a.attrs == {}


def test_capabilities_frozen_schemes():
    c = Capabilities(schemes=frozenset({"file", "swarm"}), supports_search=True, supports_delete=True, supports_promote=True)
    assert "file" in c.schemes


def test_ref_meta():
    m = RefMeta(ref="ref:file:x", scheme="file", tags=["a"], block_type="knowledge")
    assert m.ref.startswith("ref:")
