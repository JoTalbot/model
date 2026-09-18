# CONSENT GATES — All Human Approval Points (2026-06-19)

## Mandatory before any action
1. Provisioning any new node (free-tier or third-party)
2. Starting MCP daemon in production
3. Enabling reproduction (child nodes)
4. Adding new skills to marketplace
5. Running chaos tests that affect live nodes
6. Any paid resource (even $1)

## How it works
- human_consent.env file per node/project
- Explicit "YES" in chat or PR comment
- Log consent in /run/octopus/consent_log.json
- No action without recorded consent

## Emergency
- Self-healing + autoheal can run without consent (but log + notify)
- Critical security patches can be fast-tracked with minimal consent
