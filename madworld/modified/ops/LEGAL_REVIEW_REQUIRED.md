# B10 Legal / Privacy Review

Status: **DOCUMENTATION IMPLEMENTED — FINAL EXTERNAL LEGAL REVIEW / STORE PUBLICATION STILL REQUIRED WHERE APPLICABLE.**

On 2026-09-08 the release owner authorized autonomous completion of the repository-side privacy, terms, data-safety and deletion documentation.

Current repository disclosures:

- `docs/PRIVACY_POLICY.md`
- `docs/TERMS_OF_SERVICE.md`
- `docs/DATA_SAFETY.md`
- `docs/ACCOUNT_DELETION.md`

These documents are intentionally conservative and do not claim third-party providers that are outside the release scope. They require final jurisdiction-specific legal review where applicable and must be published at a stable public location before public launch.

## Current data processing boundary

- Players authenticate through Bearer session tokens issued by the MadWorld API.
- Server-authoritative state is persisted in PostgreSQL, including player/game state and operational records required by the service.
- `analytics_events` may exist in the database schema, but no external analytics provider is required for this release.
- Firebase/FCM push is removed from the release scope. Migration `035_remove_firebase_push_tokens.sql` removes the obsolete provider-token registry; no provider token registration or delivery path is required for this release.
- External crash reporting is not configured and is excluded from the release scope.
- The Android application requires network access for the online service; Android notification permission behavior is not a release dependency because push is out of scope.

## Owner decisions recorded

- **Push notifications:** not required for this release; Firebase/FCM is removed from release scope.
- **Crash reporting:** not required for this release.
- **Analytics:** not required for this release.
- **Privacy/Terms/Data Safety:** owner approved autonomous repository implementation; independent legal review remains required where applicable.
- **Deletion:** an operational deletion workflow is documented. The repository must not claim fully automated account deletion until an implementation endpoint is verified; support-mediated deletion is the documented current process.

## Remaining external/legal gate

1. Publish the final Privacy Policy and Terms at stable public URLs with a valid operator/support contact.
2. Complete store data-safety/content declarations consistently with the exact production artifact.
3. Verify or operationally test the documented account-deletion process against the production account/data model.
4. Complete applicable age/content and jurisdictional review.

Until these are evidenced, the legal/publication gate remains `PARTIALLY VERIFIED` and the build remains a Release Candidate rather than a public production release.
