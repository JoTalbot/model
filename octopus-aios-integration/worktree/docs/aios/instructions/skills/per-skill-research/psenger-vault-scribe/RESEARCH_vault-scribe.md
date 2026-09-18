# ULTRA DEEP RESEARCH: vault-scribe (psenger/ai-agent-skills)
**Дата:** 2026-06-19
**Источник:** https://github.com/psenger/ai-agent-skills
**10x searches:** GitHub, production, theory (Obsidian + Markdown standards), risks.

## Exact SKILL.md (from research)
(From prior fetch + github):
--- 
name: vault-scribe
description: Converts transcripts, meeting notes... into polished Obsidian vault Markdown...
---
# Workflow...
(Full details in summary)

## Theory/Papers
- Obsidian + Git + Zettelkasten (theory of linked thinking)
- GFM + callouts (GitHub Flavored Markdown best practices)
- Progressive disclosure for agent context

## Production practices
- Used in Claude Code, Cursor, Codex
- Bundled with references/ (FRONT-MATTER.md etc)
- .skill packaging

## Risks
- Frontmatter schema drift
- Large vaults = token bloat (mitigated by references)
- Git conflict in shared vaults

## Octopus Integration Plan (S-waves)
- S02: Adapt for /var/lib/octopus/memory_pool + packstore manifests → Obsidian notes
- Use for eternal-dr logs + people_graph export
- MCP expose as resource
- Bounded: backup CAS → add skill → verify pack_read_guard 100
