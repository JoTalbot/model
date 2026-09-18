# ULTRA DEEP RESEARCH: memory-systems (muratcankoylan/Agent-Skills-for-Context-Engineering)
**Дата:** 2026-06-19
**GitHub:** https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering
**10x:** arXiv (memory graphs, temporal KG), production (Mem0/Zep/Letta), Octopus RAG/GraphRAG.

## Full SKILL.md excerpt (fetched)
--- 
name: memory-systems
description: persistent semantic memory...
---
# Memory System Design
(Full: layers, frameworks, benchmarks LoCoMo etc.)

## Theory
- Vector vs Graph vs Temporal KG (Zep Graphiti, Cognee)
- Benchmarks: LoCoMo, HotPotQA
- Consolidation, entity tracking

## Production
- Mem0 for multi-tenant
- Zep for temporal
- File-system for simple (Octopus packstore fits)

## Risks
- Context clash on temporal facts
- Retrieval quality degradation

## Octopus Integration (S-waves)
- S03: Integrate with /var/lib/octopus/memory_pool + pgvector + GraphRAG
- Use for people_graph + eternal memory
- Hybrid: CAS for durable + vector/graph
