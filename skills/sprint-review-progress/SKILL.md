---
name: sprint-review-progress
description: Sprint-review progress report for Team A/C on Jira. Matches the Team A/C roadmap items to Jira epics and reports, per sprint and overall, how many tasks are done, in progress, or not started. Use when the user asks for sprint review data, sprint progress, roadmap item progress, or says اسپرینت ریویو، پیشرفت اسپرینت، پیشرفت آیتم‌ها.
---

# Sprint review progress (Team A/C)

## Run

```bash
python C:/Users/PC/.claude/skills/sprint-review-progress/scripts/sprint_progress.py --open
```

Writes a self-contained, bilingual (EN/FA button, top right) HTML report to `~/sprint-review/sprint-review-<quarter>-<date>.html`, plus an English Markdown copy (`.md`), prints a short summary in the terminal, and with `--open` opens the HTML in the browser.

The HTML has tabs: Overall, Releases, and one tab per sprint. Every row with a list button expands the tasks behind it (key, summary, colored status, assignee, Story Points). Releases (open and released) have an info button that shows the Jira description. Each sprint tab also lists the tasks that sit in a roadmap epic with no matching fix version, and the tasks outside the roadmap table (grouped by epic).

Options: `--quarter 2026Q4` (default; sprint name must contain it), `--include-future`, `--lang en|fa` (language the report opens in; the button switches it and the choice is remembered), `--format both|html|md`, `--out-dir <folder>`, `--open`.
Standard-library Python only. Configuration (`JIRA_BASE_URL`, `JIRA_PAT`, project, board, sprint prefix) comes from environment variables or a `.env` file; run with `--check` first to see what is used. Never print the token.

## What it reports

1. Overall: for each roadmap item (Team A/C table order), all tasks of its epics split into done / in progress / not started, with its prerequisite releases and their progress.
2. Releases: progress of each release (fix version), open ones first and released ones in their own table, with the Jira description.
3. Per sprint (board 8, sprints named `TeamAC …`, closed and active): estimated work done (Story Points), tasks done, and for each item its progress in the sprint and its overall done % at sprint start → end.

Counts are task counts, not Story Points. Epics and sub-tasks are not counted. Done = status category Done; in progress = status category In Progress (includes QA); not started = everything else (Listed).

## Mapping

`mapping.json` links each roadmap item to epics. A source can add `fixVersions` to split one epic across items (TC-85 is split by version: 8.4 vs 8.5/8.6; TC-86 by PWA-Part1 / PWA-Part2). Items with an empty `sources` list have no epic and show «—». Each item has English and Persian text (`title`/`title_fa`, `group`/`group_fa`, `prerequisites`/`prerequisites_fa`). To change what an item covers, edit this file, not the script.

The report also lists tasks that sit in a mapped epic but match no item (no matching fix version), and tasks in sprints that belong to epics outside the table.

## Answer

Reply in English (the report is English). Give the file paths and a short summary; do not paste the whole report. Do not change counts or issue keys. If the script fails, report the error and stop.
