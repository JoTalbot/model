#!/usr/bin/env python3
"""
Progressive Disclosure SKILL.md Loader for Octopus (S02 enhanced)
"""
from __future__ import annotations
import yaml
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field

SKILLS_ROOT = Path("/root/agents/-Octopus/skills")

@dataclass
class SkillMeta:
    name: str
    description: str
    path: Path
    body: Optional[str] = None
    references: Dict[str, str] = field(default_factory=dict)

class SkillsLoader:
    def __init__(self, root: Path = SKILLS_ROOT):
        self.root = root
        self._metadata_cache = {}
        self._full_cache = {}
        self.discover()

    def discover(self):
        metas = []
        for skill_file in self.root.rglob("SKILL.md"):
            if skill_file.is_file():
                meta = self._load_meta(skill_file)
                if meta:
                    self._metadata_cache[meta.name] = meta
                    metas.append(meta)
        return metas

    def _load_meta(self, skill_file):
        try:
            content = skill_file.read_text(encoding="utf-8")
            if not content.startswith("---"):
                return None
            front, _, body = content.partition("\n---\n")
            front = front.lstrip("---\n").strip()
            meta_dict = yaml.safe_load(front) or {}
            name = meta_dict.get("name", skill_file.parent.name)
            desc = meta_dict.get("description", "")
            return SkillMeta(name=name, description=desc, path=skill_file, body=body.strip() if body else None)
        except Exception:
            return None

    def list_metadata(self):
        return [{"name": m.name, "description": m.description} for m in self._metadata_cache.values()]

    def load_full(self, name):
        if name in self._full_cache:
            return self._full_cache[name]
        meta = self._metadata_cache.get(name)
        if not meta or not meta.path.exists():
            return None
        content = meta.path.read_text(encoding="utf-8")
        self._full_cache[name] = content
        return content

    def load_references(self, name):
        meta = self._metadata_cache.get(name)
        if not meta:
            return {}
        ref_dir = meta.path.parent / "references"
        if ref_dir.exists():
            return {p.name: p.read_text() for p in ref_dir.glob("*") if p.is_file()}
        return {}

    def activate_skill(self, name, context=""):
        full = self.load_full(name)
        refs = self.load_references(name)
        if not full:
            return f"Skill {name} not found"
        ref_summary = f"References loaded: {list(refs.keys())}" if refs else "No references"
        return f"[SKILL ACTIVATED: {name}]\n{full[:2500]}\n... \n{ref_summary}\nContext: {context[:300]}\n"

class SkillsPlugin:
    name = "skills_loader"

    def __init__(self):
        self.loader = SkillsLoader()

    async def setup(self, container):
        if hasattr(container, "plugin_registry") and container.plugin_registry:
            pr = container.plugin_registry
            pr.register_command("list_skills", lambda p: self.loader.list_metadata())
            pr.register_command("load_skill", lambda p: self.loader.load_full(p.get("name")))
            pr.register_command("activate_skill", lambda p: self.loader.activate_skill(p.get("name", ""), p.get("context", "")))
            pr.register_command("load_references", lambda p: self.loader.load_references(p.get("name")))
        print("[Octopus Skills S02] Enhanced progressive loader registered (8 skills)")

skills_loader = SkillsLoader()
