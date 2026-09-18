from __future__ import annotations

PREFIX = "ref:"


class RefFormatError(ValueError):
    pass


def make_ref(scheme: str, opaque: str) -> str:
    if not scheme or ":" in scheme:
        raise RefFormatError("invalid scheme")
    if opaque is None or opaque == "":
        raise RefFormatError("opaque must be non-empty")
    return f"{PREFIX}{scheme}:{opaque}"


def parse_ref(ref: str) -> tuple[str, str]:
    if not ref.startswith(PREFIX):
        raise RefFormatError("ref must start with ref:")
    rest = ref[len(PREFIX) :]
    idx = rest.find(":")
    if idx <= 0 or idx == len(rest) - 1:
        raise RefFormatError("ref must be ref:<scheme>:<opaque>")
    scheme, opaque = rest[:idx], rest[idx + 1 :]
    if not scheme:
        raise RefFormatError("empty scheme")
    return scheme, opaque
