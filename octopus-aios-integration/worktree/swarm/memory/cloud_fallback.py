"""Cloud paste fallback order for ``--store auto`` and smoke checks."""

from __future__ import annotations

from typing import Any


def cloud_auto_fallback_schemes(cfg: dict) -> list[str]:
    """Return ordered scheme names for resilient ``put`` attempts.

    * If ``memory_facade.cloud_paste.auto_fallback_order`` is a non-empty list,
      those names are used first (after stripping); ``file`` is appended if
      absent so local scratch is always a last resort.
    * Otherwise uses a built-in priority among **enabled** ``cloud_paste``
      flags, then ``file``.
    """
    mf = cfg.get("memory_facade") or {}
    cloud: dict[str, Any] = dict(mf.get("cloud_paste") or {})
    raw = cloud.get("auto_fallback_order")
    if isinstance(raw, list) and raw:
        out = [str(x).strip() for x in raw if str(x).strip()]
    else:
        default_order = (
            "pasters",
            "catbox",
            "sprunge",
            "tmpfiles",
            "fileio",
            "nullpointer",
            "pasteee",
            "ixio",
            "telegraph",
            "rentry",
            "dpaste",
            "termbin",
            "transfersh",
        )
        out = [s for s in default_order if cloud.get(s)]
    if "file" not in out:
        out.append("file")
    return out


async def repository_save_with_store_fallback(
    repo,
    *,
    data: dict[str, Any],
    table: str,
    tags: list[str],
    attrs_base: dict[str, Any],
    schemes: list[str],
) -> tuple[str, str]:
    """Try ``repo.save`` with ``attrs["store"]`` set to each scheme until one works.

    Returns ``(ref, scheme_used)``. Raises the last exception if all fail.
    """
    last: BaseException | None = None
    for sch in schemes:
        attrs = {**attrs_base, "store": sch}
        try:
            ref = await repo.save(data=data, table=table, tags=tags, attrs=attrs)
            return ref, sch
        except BaseException as exc:
            last = exc
            continue
    if last is None:
        raise RuntimeError("no fallback schemes")
    raise last
