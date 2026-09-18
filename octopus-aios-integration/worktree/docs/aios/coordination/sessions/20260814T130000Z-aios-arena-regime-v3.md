# Сессия: Regime-filter Directional v3

---
session_id: "20260814T130000Z-aios-arena-regime-v3"
status: "DONE"
agent: "Arena.ai Agent Mode"
machine: "aios"
started_utc: "2026-08-14T13:00:00Z"
updated_utc: "2026-08-14T13:30:00Z"
branch: "agent/20260814-regime-v3"
base_commit: "3a688a30"
claim: "coordination/claims/regime-v3--20260814T130000Z-aios-arena-regime-v3.md"
---

## Цель

Реализовать regime features и rolling multi-fold v3 на 5 000 закрытых 1h свечей. Runtime остаётся paper/freeze.

## Scope

EMA slope/ADX proxy, ATR percentile, volume/range liquidity, freshness, correlation clusters, regime classifier, rolling folds, cost stress ×1.5 и v3 gate.

## Результат

15 активов, 90 OOS folds: median −0.754%, positive 8.9%, costs×1.5 median −1.158%. Gate не пройден; freeze сохранён.
