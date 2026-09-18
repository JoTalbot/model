# B10 Owner Gate Evidence

Date: 2026-09-08

This is the conservative evidence register for the remaining environment/owner gates. Repository configuration and CI success do not count as production evidence unless explicitly identified as repository-side verification.

## Owner decision record

Owner: `jo.talbot@gmail.com`

The product owner explicitly authorizes the following release decisions:

- Push notifications: **NOT REQUIRED FOR THIS RELEASE**. Push/Firebase/FCM is removed from release scope. No provider configuration or delivery test is required for this release.
- Crash reporting: **NOT REQUIRED** for this release; owner waiver granted.
- Analytics: **NOT REQUIRED** for this release; owner waiver granted.
- Privacy Policy / Terms / Data Safety / deletion: **ACCEPTED AS A RELEASE REQUIREMENT**. Product owner authorizes repository implementation and publication of the required disclosures before public launch; this owner decision does not constitute independent legal advice or external legal review.
- Incident ownership/on-call: **OWNER ACCEPTED**. Product owner `jo.talbot@gmail.com` is responsible for incident ownership and on-call for this release.
- Severity-5 disaster clamp: **APPROVED** by the product owner as intended gameplay behavior.
- Production capacity threshold: **OWNER APPROVED** for the repository-defined acceptance boundary in `ops/CAPACITY_ACCEPTANCE.md`; the controlled queue-depth/recovery run remains required evidence.
- Rollback rehearsal: **OWNER APPROVED** to execute against the documented MadWorld release procedure, with the existing production-safety boundaries preserved.

These owner decisions do not substitute for technical evidence that must still be executed, especially the remaining Android API matrix, controlled capacity queue-depth/recovery evidence, rollback rehearsal, and any independent legal review required outside the repository.

## Evidence status

- [x] Production domain/DNS/TLS/reverse proxy verified on the real host. Evidence: `ops/PROD_HARDENING_EVIDENCE_2026-09-03.md`.
- [x] Scheduled PostgreSQL backup installed and observed running under `/opt/madworld/backups`. Evidence: `ops/B10_PROD_DR_RPO_EVIDENCE_2026-09-04.md`.
- [x] Backup retention, SHA-256 manifest, integrity check and low-disk fail-closed behavior observed in the target environment. Evidence: `ops/B10_PROD_DR_RPO_EVIDENCE_2026-09-04.md`.
- [x] RPO target <=24h is supported by the daily scheduled production backup. A measured data-loss RPO is not claimed. Evidence: `ops/B10_PROD_DR_RPO_EVIDENCE_2026-09-04.md`.
- [x] Fresh isolated recovery rehearsal completed and measured RTO recorded: `cmd-20260907-162000-dr-isolated-rehearsal-direct-v4`, exit code 0, measured RTO 1.015s, production database untouched.
- [x] Production-like capacity threshold approved in `ops/CAPACITY_ACCEPTANCE.md`; controlled queue-depth/recovery run remains open.
- [ ] Controlled isolated capacity run completed with queue-depth/recovery evidence.
- [ ] Android API 26 validation.
- [ ] Android API 29-32 validation.
- [x] Android API 33-35 physical-device validation: G1 / Android 15 / API 35, user-reported manual validation on 2026-09-08, all recorded checks PASS.
- [x] Physical Android device verification completed for API 35.
- [x] Physical-device offline queue, reconnect/resume, stale-state and network-loss validation completed for API 35.
- [x] Push/Firebase/FCM removed from release scope. No provider configuration or delivery test is required.
- [x] Crash reporting explicitly waived by product owner for this release.
- [x] Analytics explicitly waived by product owner for this release.
- [ ] Privacy Policy, Terms, Data Safety and deletion disclosures implemented/published and externally reviewed where required.
- [x] Incident ownership/on-call owner assigned: `jo.talbot@gmail.com`.
- [ ] Rollback rehearsal completed.
- [x] Isolated disaster-recovery rehearsal completed: `cmd-20260907-162000-dr-isolated-rehearsal-direct-v4`, exit code 0.
- [x] Severity-5 disaster clamp behavior explicitly approved by the product owner.
- [x] Immutable evidence attached for the currently executed technical rehearsals.
- [ ] Final production artifact/tag decision approved after all mandatory technical and publication gates above.

## Repository-side verification that does NOT close external gates

- Exact-head Backend CI and Release Gate must be rerun after consequential release-gate changes.
- Isolated GitHub Actions backup/restore verification: `ops/B10_GITHUB_DR_EVIDENCE_2026-09-04.md`.
- Repository-side capacity/resilience evidence: `ops/B10_CAPACITY_CI_EVIDENCE.md`.
- Android network-resilience requirements: `ops/B10_ANDROID_NETWORK_RESILIENCE.md`.

## Capacity evidence

- Read-only isolated baseline: `cmd-20260907-123000-capacity-isolated-v8`, DONE, exit 0, 5060/5060 successful, 168.667 RPS, p95 126.978 ms, p99 219.084 ms, 0 application errors, world-tick lag 0.
- Mutation/idempotency/security rehearsal: `cmd-20260907-170000-full-capacity-v5`, DONE, exit 0, 2515/2515 successful mutations, 167.667 RPS, p95 154.022 ms, p99 181.860 ms, authentication 401, application idempotency PASS, replay containment PASS, world-tick lag 0.
- Both rehearsals used isolated PostgreSQL 16/API/worker containers and explicitly reported `PRODUCTION_DATABASE_TOUCHED=false`.
- Owner-approved production-equivalent acceptance boundary is documented in `ops/CAPACITY_ACCEPTANCE.md`; no production stress test is authorized by this record.

## Target-environment recovery evidence

- Production scheduled backup and isolated recovery evidence: `ops/B10_PROD_DR_RPO_EVIDENCE_2026-09-04.md`.
- Latest verified backup was restored into a separate MadWorld-only PostgreSQL 16 container without production interruption.
- Isolated restore verification succeeded with `restore_verified=1` and `schema_migrations=41`.
- The temporary DR container, volume and network were subsequently confirmed absent from the server.
- A post-cleanup production safety check showed the MadWorld API and PostgreSQL containers healthy, with public `/health/ready` returning `status=ok`, `database=ok`, and `migrations_applied=41`.
- The 2026-09-07 fresh isolated DR rehearsal measured RTO 1.015s and did not touch the production database.
- This does not close the target-recovery-environment approval gate until the required rollback/recovery rehearsal has terminal evidence.

## Current decision

**B10: GO AFTER REMAINING TECHNICAL/PUBLICATION EVIDENCE**

Do not mark B10 production GREEN, create the final production tag, or publish the production release until the unchecked technical/publication evidence is attached to the release candidate and the exact-head Release Gate passes.

## Safety boundary

This evidence register and B10 repository work do not modify Octopus or its infrastructure. Do not touch `/opt/octopus`, `/var/lib/octopus`, `/etc/octopus`, existing PostgreSQL infrastructure, existing Docker networks/volumes, host port 8000, global Docker cleanup, or UFW as part of this gate unless separately authorized and required.
