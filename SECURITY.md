# Reporting a vulnerability

Open the [Security tab](https://github.com/rezono-lang/rezono/security) and choose **Report a vulnerability** to send the maintainers a confidential report. Include the affected revision, the impact and enough detail for the maintainers to investigate.

## Dependency updates

Dependabot groups ordinary version updates weekly. Security updates are handled separately as alerts arrive. The maintainer for the affected component owns its alerts and update pull requests.

- Assign an immediate repair for critical or high alerts affecting a release or image. Give it priority over other work.
- Critical or high alerts confined to unreleased tests, oracles or tools need a merged repair or a record in `blocked/` within 24 hours of the alert.
- Medium and low alerts need a repair within a week or in the weekly update.

When an update fails a check, repair it or record the alert, affected manifest and version, and the failing evidence in `blocked/`. Use `yq -o=json .github/dependabot.yml | python3 -I scripts/test_dependabot.py` to check manifest coverage. Review the deployment overlays' Kustomize image pins separately because Dependabot's Docker updater does not read those replacements.
