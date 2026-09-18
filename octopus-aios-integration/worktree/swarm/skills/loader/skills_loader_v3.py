#!/usr/bin/env python3
"""Skills Loader v3.1 - L0/L1/L2 tiered loading with duplicate-safe IDs."""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

SKILLS_BASE = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
CATEGORIES = ["core", "dr", "loader", "marketplace", "mcp", "memory", "meta", "research", "swarm"]


def parse_yaml_frontmatter(text: str) -> dict:
    fm = {}
    for raw in text.split("\n"):
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if val.startswith('"') and val.endswith('"'):
            val = val[1:-1]
        elif val.startswith("'") and val.endswith("'"):
            val = val[1:-1]
        if val.startswith("[") and val.endswith("]"):
            items = [x.strip().strip('"').strip("'") for x in val[1:-1].split(",") if x.strip()]
            fm[key] = items
        elif val.lower() in ("true", "false"):
            fm[key] = val.lower() == "true"
        else:
            fm[key] = val
    return fm


class SkillMeta:
    def __init__(self, name: str, version: str = "1.0", description: str = "", triggers=None,
                 dependencies=None, llm_required: bool = False, mcp_tools=None):
        self.name = name
        self.version = version
        self.description = description
        self.triggers = triggers or []
        self.dependencies = dependencies or []
        self.llm_required = llm_required
        self.mcp_tools = mcp_tools or []

    def to_dict(self) -> dict:
        return vars(self).copy()


class Skill:
    def __init__(self, path: Path, category: str):
        self.path = Path(path)
        self.category = category
        self.dir_name = self.path.name
        self.id = f"{category}/{self.dir_name}"
        self.name = self.dir_name
        self.meta = SkillMeta(name=self.name)
        self.has_description = False
        self.has_algorithm = False
        self.has_code = False
        self.has_tests = False
        self._parse()

    def _parse(self) -> None:
        skill_file = self.path / "SKILL.md"
        if not skill_file.exists():
            return
        content = skill_file.read_text(encoding="utf-8", errors="replace")
        frontmatch = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if frontmatch:
            fm = parse_yaml_frontmatter(frontmatch.group(1))
            self.meta = SkillMeta(
                name=fm.get("name", self.dir_name),
                version=str(fm.get("version", "1.0")),
                description=fm.get("description", ""),
                triggers=fm.get("triggers", []),
                dependencies=fm.get("dependencies", []),
                llm_required=fm.get("llm_required", False),
                mcp_tools=fm.get("mcp_tools", [])
            )
        self.name = self.meta.name
        body = content[frontmatch.end():] if frontmatch else content
        self.has_description = bool(re.search(r"description:\s*.+|##\s*Описани[ея]", content, re.I))
        self.has_algorithm = bool(re.search(r"##\s*Алгоритм", body))
        code_dir = self.path / "code"
        test_dir = self.path / "tests"
        self.has_code = (self.path / "code.py").exists() or (code_dir / "run.py").exists() or (code_dir.exists() and any(p.is_file() and p.name != "__pycache__" for p in code_dir.iterdir()))
        self.has_tests = test_dir.exists() and any(p.is_file() for p in test_dir.rglob("*.py"))

    def is_stub(self) -> bool:
        # In v3.1 a real skill must have an algorithm, executable runtime, and contract tests.
        return not (self.has_algorithm and self.has_code and self.has_tests)

    def to_index_record(self) -> dict:
        d = self.meta.to_dict()
        d.update({
            "id": self.id,
            "category": self.category,
            "dir_name": self.dir_name,
            "path": str(self.path),
            "has_description": self.has_description,
            "has_algorithm": self.has_algorithm,
            "has_code": self.has_code,
            "has_tests": self.has_tests,
            "stub": self.is_stub(),
        })
        return d

    def __repr__(self) -> str:
        stub = " [STUB]" if self.is_stub() else ""
        return f"Skill({self.id} name={self.name}{stub})"


class SkillsLoaderV3:
    def __init__(self, skills_base=None):
        self.skills_base = Path(skills_base) if skills_base else SKILLS_BASE
        self.skills_by_id: Dict[str, Skill] = {}
        self.skills_by_name: Dict[str, List[Skill]] = defaultdict(list)
        # Backward-compatible alias; canonical keys are category/name IDs.
        self.skills = self.skills_by_id
        self._scan_all()

    def _scan_all(self) -> None:
        for cat in CATEGORIES:
            cat_path = self.skills_base / cat
            if not cat_path.exists():
                continue
            for d in sorted(cat_path.iterdir()):
                if d.is_dir() and (d / "SKILL.md").exists():
                    skill = Skill(d, cat)
                    self.skills_by_id[skill.id] = skill
                    self.skills_by_name[skill.name].append(skill)

    def get_stubs(self) -> List[Skill]:
        return [s for s in self.skills_by_id.values() if s.is_stub()]

    def get_real(self) -> List[Skill]:
        return [s for s in self.skills_by_id.values() if not s.is_stub()]

    def audit(self) -> dict:
        stubs = self.get_stubs()
        real = self.get_real()
        categories = {}
        for cat in CATEGORIES:
            cat_path = self.skills_base / cat
            if cat_path.exists():
                categories[cat] = len([d for d in cat_path.iterdir() if d.is_dir() and (d / "SKILL.md").exists()])
        duplicates = {name: [s.id for s in skills] for name, skills in sorted(self.skills_by_name.items()) if len(skills) > 1}
        return {
            "total": len(self.skills_by_id),
            "unique_names": len(self.skills_by_name),
            "real_skills": len(real),
            "stubs": len(stubs),
            "stub_ids": sorted([s.id for s in stubs]),
            "stub_names": sorted([s.name for s in stubs]),
            "real_ids": sorted([s.id for s in real]),
            "real_names": sorted(set(s.name for s in real)),
            "duplicate_names": duplicates,
            "duplicate_count": len(duplicates),
            "categories": categories,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def save_index(self, path=None) -> dict:
        path = Path(path) if path else self.skills_base / "index.json"
        audit = self.audit()
        data = {
            "version": "3.1",
            "timestamp": audit["timestamp"],
            "audit": audit,
            "skills": {sid: s.to_index_record() for sid, s in sorted(self.skills_by_id.items())},
            "skills_by_name": {name: [s.id for s in skills] for name, skills in sorted(self.skills_by_name.items())},
        }
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return data


if __name__ == "__main__":
    loader = SkillsLoaderV3()
    audit = loader.audit()
    print("=== SKILLS AUDIT ===")
    print(f"Total IDs:     {audit['total']}")
    print(f"Unique names:  {audit['unique_names']}")
    print(f"Real:          {audit['real_skills']}")
    print(f"Stubs:         {audit['stubs']}")
    print(f"Duplicates:    {audit['duplicate_count']}")
    if audit["duplicate_names"]:
        for name, ids in audit["duplicate_names"].items():
            print(f"  - {name}: {', '.join(ids)}")
    print(f"Categories: {audit['categories']}")
    if audit["stub_ids"]:
        print(f"\nStub skill IDs ({len(audit['stub_ids'])}):")
        for n in audit["stub_ids"]:
            print(f"  - {n}")
    loader.save_index()
    print("\nIndex saved.")
