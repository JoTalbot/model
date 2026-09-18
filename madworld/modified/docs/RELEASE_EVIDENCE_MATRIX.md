# MadWorld Release Evidence Matrix

This file maps release gates to concrete evidence. It is a truth map, not a prediction.

## Status vocabulary

- `VERIFIED` — concrete evidence proves the stated gate for the stated boundary.
- `PARTIALLY VERIFIED` — useful evidence exists, but a required part remains open.
- `NOT VERIFIED` — required evidence is absent.
- `NOT EXECUTED` — the operation was not performed.
- `FAILED` — execution/evidence failed.
- `UNKNOWN` — evidence is contradictory or terminal state cannot be established.

## Current matrix

| Gate | Evidence | Boundary / freshness | Status | Remaining action |
|---|---|---|---|---|
| Repository / backend CI | GitHub Actions backend gate | candidate | PARTIALLY VERIFIED | rerun on exact final release commit |
| Android unit/debug/release build | Android CI + release artifact | candidate | VERIFIED | remaining API matrix is separate |
| Production deployment | deployment run + exact deployed commit + service/runtime checks | deployed candidate | VERIFIED | recheck after release-affecting changes |
| Public API health | public `/health/ready` response | live deployment | VERIFIED | recheck after release-affecting changes |
| Public TLS | certificate/chain verification | live deployment | VERIFIED | recheck after certificate/DNS changes |
| Backup automation | timer state + latest backup/checksum | production | VERIFIED | continue operational monitoring |
| Isolated DR | Remote Operator result, restore verification, migration count, RTO | ephemeral PostgreSQL 16 | VERIFIED | rollback/target-recovery rehearsal remains separate |
| Read capacity | isolated 20-client / 30s rehearsal | ephemeral PostgreSQL 16 + API + worker | VERIFIED | preserve evidence |
| Mutation capacity | isolated concurrent POST rehearsal | ephemeral PostgreSQL 16 + API | VERIFIED | preserve evidence |
| Auth / idempotency / replay | full isolated rehearsal | ephemeral environment | VERIFIED | none for isolated gate |
| World tick under load | isolated worker ticks and lag | ephemeral environment | VERIFIED | preserve regression coverage |
| Production-equivalent capacity acceptance | owner-approved threshold + controlled queue-growth/recovery evidence | release boundary | PARTIALLY VERIFIED | execute controlled bounded run and record queue-depth/recovery |
| Android API/device matrix | API 26 / 29–32 / 33–35 + physical/emulator coverage | release environment | PARTIALLY VERIFIED | API 26 and API 29–32 still require evidence; API 35 physical validation recorded |
| Push notifications | owner decision | release scope | WAIVED | explicitly removed from this release scope |
| Crash reporting | owner waiver | release scope | WAIVED | none |
| Analytics | owner waiver | release scope | WAIVED | none |
| Privacy / terms / data safety / deletion | repository disclosures + owner approval; independent legal review where required | release | PARTIALLY VERIFIED | publish/verify final public location and complete any required external legal review |
| Incident/on-call ownership | named owner + rehearsal | external/owner | PARTIALLY VERIFIED | rollback rehearsal remains |
| Severity-5 disaster clamp interpretation | owner decision | external/owner | VERIFIED | owner approval recorded |
| Public publication | all required gates closed | release | NOT VERIFIED | blocked by remaining technical/publication evidence |

## Rules

1. Every `VERIFIED` row must have concrete evidence.
2. Evidence is tied to a candidate/commit or environment boundary.
3. A successful workflow or command does not automatically make a release gate PASS.
4. Unknown external conditions never become PASS by assumption.
5. When code/config changes after verification, reassess every affected row.
6. Keep large logs in GitHub artifacts; keep this matrix concise.

## Maintenance

Update this matrix in the same logical batch as consequential release-gate work. Never invent measurements, approvals, thresholds or external state.
