import pytest

from swarm.memory.ref_parse import make_ref, parse_ref


def test_parse_round_trip():
    r = make_ref("swarm", "abc-123")
    assert r == "ref:swarm:abc-123"
    scheme, opaque = parse_ref(r)
    assert scheme == "swarm"
    assert opaque == "abc-123"


def test_parse_https_opaque_may_contain_colons():
    opaque = "example.com%2Fpath"  # caller may URL-encode; parser must not split extra colons
    r = make_ref("https", opaque)
    scheme, out = parse_ref(r)
    assert scheme == "https"
    assert out == opaque


def test_parse_rejects_bad_prefix():
    from swarm.memory.ref_parse import RefFormatError

    with pytest.raises(RefFormatError):
        parse_ref("swarm:abc")
