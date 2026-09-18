# MadWorld Data Safety Disclosure

**Effective date:** 2026-09-08

This document is the repository source for the MadWorld store data-safety disclosure. Final store-console declarations must be kept consistent with the production build and backend configuration.

## Data categories

| Data category | Purpose | Shared with third parties | User-controlled deletion |
|---|---|---|---|
| Account / authentication identifiers | Account access and player identity | No advertising/analytics sharing | Yes, subject to legitimate retention exceptions |
| Gameplay / player state | Persistent game operation | No advertising/analytics sharing | Yes, subject to legitimate retention exceptions |
| Security / audit information | Abuse prevention, integrity and incident investigation | Only where operationally necessary | May be retained temporarily for security/legal reasons |
| Technical operational information | Reliability, troubleshooting and service security | Operational infrastructure only where necessary | Subject to normal log/backup retention |
| Support requests | Responding to users and account requests | No advertising sharing | Yes, subject to legitimate retention exceptions |

## Collection and use

MadWorld processes only information needed to operate the online game, secure the service, maintain persistent state, and provide support. The release does not require third-party advertising, third-party analytics, or push/Firebase/FCM services.

## Security

Data is protected through authenticated access, server-authoritative state changes, transactional persistence, access controls, backups, and operational security controls appropriate to the service.

## Deletion

Users can request account and associated data deletion by contacting **jo.talbot@gmail.com**. The operator verifies account control before processing the request. Data that must temporarily remain for security, fraud prevention, legal obligations, or backup recovery is handled according to the retention rules in the Privacy Policy.

## Store declaration note

The store's final data-safety/content declarations must be reviewed against the exact production artifact before publication. This repository document is not a substitute for completing the applicable store-console questionnaire.
