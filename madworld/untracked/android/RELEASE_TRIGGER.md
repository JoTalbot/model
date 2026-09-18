# Android release artifact trigger

This file exists to trigger Android CI for repository-only changes so the current production-configured APK is rebuilt and published as a GitHub Actions artifact.

Production API: `https://api.autosklo.org.ua`

Release builds must use HTTPS and must not use emulator-only `10.0.2.2` routing.
