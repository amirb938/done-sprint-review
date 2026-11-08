# Changelog

## Unreleased

- Sprint goal from the Jira sprint shown at the top of each sprint tab and of the Overall tab. Optional Persian text in `mapping.json` under `sprint_goals_fa`.
- «Names» button next to EN/FA shows or hides the assignee column (remembered in the browser).
- Task lists are ordered Done, QA, In Progress, Listed, and keep Jira's rank order inside each group. Rows can be dragged to reorder; the order is remembered in the browser and can be reset.
- Progress bars separate QA from In Progress. The big percentage cards mark how far the work has got up to Done, QA and In Progress.
- `mapping.json`: PWA-Part2 now belongs to phase 0 (with PWA-Part1); the phase 1 item has no epic yet. Release names follow the current Jira versions.

## 1.0.0

First release.

- Overall, Releases and per-sprint tabs, with progress per roadmap item, estimated work (days) and item movement from sprint start to end.
- Task lists behind every row, including work outside the roadmap table and tasks with no matching fix version.
- Open and released versions with their Jira description.
- Bilingual report (EN/FA with RTL), light and dark mode, print-friendly, single file.
- Configuration through `.env` (token, project, board, sprint prefix, quarter), `--check`, and clear errors for a wrong token or board.
- Claude Code skill and install scripts for bash and PowerShell.
