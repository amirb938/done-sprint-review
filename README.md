# done-sprint-review

Sprint-review reporting for Team A/C, straight from Jira. One command builds a bilingual (EN/FA) HTML report that answers the questions asked in every sprint review:

- **Where are we on each roadmap item?** Progress per item, with the epics and the prerequisite releases behind it.
- **What did this sprint move?** Estimated work done (Story Points), tasks done, and each item's progress from sprint start to sprint end.
- **Where is each release?** Open and released versions, with the Jira description one click away.
- **What is behind every number?** Every row opens the task list: key, summary, status, assignee, Story Points.

It is a plain Python script (standard library only, no `pip install`) and also ships as a [Claude Code](https://claude.com/claude-code) skill, so you can ask Claude for the report in plain words.

The script **only reads** from Jira. It never creates or changes anything there.

## Quick start

```bash
git clone https://github.com/amirb938/done-sprint-review.git
cd done-sprint-review

cp .env.example .env          # then put your Jira URL and token in .env
python skills/sprint-review-progress/scripts/sprint_progress.py --check   # verify the connection
python skills/sprint-review-progress/scripts/sprint_progress.py --open    # build and open the report
```

Requirements: Python 3.9+ and a Jira Data Center / Server with the Agile board API. No other dependencies.

`--check` prints who you are signed in as, the project, board, field ids and mapping that will be used, so a wrong setting is obvious before the real run.

## Configuration (`.env`)

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `JIRA_BASE_URL` | yes | | Jira base URL, no trailing slash |
| `JIRA_PAT` | yes | | Personal Access Token. Read access is enough |
| `JIRA_PROJECT` | no | `TC` | Project key to report on |
| `JIRA_BOARD_ID` | no | from `mapping.json` | Board that owns the sprints |
| `SPRINT_PREFIX` | no | from `mapping.json` | Only sprints starting with this are reported, e.g. `TeamAC` |
| `SPRINT_QUARTER` | no | current quarter | Sprints whose name contains this, e.g. `2026Q4` |
| `JIRA_STORY_POINTS_FIELD` | no | found by name | Field id, e.g. `customfield_10106` |
| `JIRA_EPIC_LINK_FIELD` | no | found by name | Field id of *Epic Link* |
| `MAPPING_FILE` | no | bundled `mapping.json` | Path to your own mapping |
| `REPORT_OUT_DIR` | no | `~/sprint-review` | Where reports are written |

Real environment variables win over `.env`. The `.env` file is looked for, in order, at `--env-file`, `$SPRINT_REVIEW_ENV`, the current folder, the repo root and `~/.sprint-review.env`.

**The token stays in `.env`, which git ignores.** Only `.env.example` (placeholders) is committed. If a token is ever pasted somewhere it should not be, revoke it in Jira and create a new one.

## Command line

```text
sprint_progress.py [--check] [--open] [--quarter 2026Q4] [--include-future]
                   [--lang en|fa] [--format both|html|md]
                   [--out-dir DIR] [--env-file FILE]
```

| Option | What it does |
|---|---|
| `--check` | Test the connection and show the effective configuration, then exit |
| `--open` | Open the HTML report in the browser (Windows) |
| `--quarter` | Which sprints to include (name contains it) |
| `--include-future` | Also report sprints that have not started |
| `--lang` | Language the report opens in. The EN/FA button switches it later |
| `--format` | `html`, `md`, or `both` (default). The Markdown copy is English |

Output: `sprint-review-<quarter>-<date>.html` (and `.md`) plus a short summary in the terminal.

## The report

| Tab | Content |
|---|---|
| **Overall** | Every roadmap item in the Team A/C table order: progress bar, epics, prerequisite releases, notes, and the task list |
| **Releases** | Open releases, then released ones, each with its progress and the Jira description |
| **Sprint …** | One tab per sprint: estimated work done, tasks done, how each item moved from start to end, and the other work in the sprint |

The report is a single self-contained file: it works offline, in light and dark mode, on a phone, and prints cleanly. Done = Jira status category *Done*; in progress = *In Progress* (QA included); everything else is not started. Epics and sub-tasks are not counted.

## Mapping: roadmap items to epics

`skills/sprint-review-progress/mapping.json` is the only thing you edit to change what the report means.

```jsonc
{
  "board_id": 8,
  "sprint_prefix": "TeamAC",
  "items": [
    {
      "group": "Acquire new users on Done",
      "title": "Mature the new Done UI",
      "title_fa": "…",                      // Persian text for the FA view
      "team": "Team A/C",
      "sources": [{ "epic": "TC-85", "fixVersions": ["8.4"] }],
      "prerequisite_releases": ["8.2", "8.3"],
      "prerequisites": "Why these come first.",
      "prerequisites_fa": "…"
    }
  ],
  "release_overview": ["8.2", "8.3", "8.4"]
}
```

- `sources` links the item to epics. Add `fixVersions` to **split one epic across several items** (TC-85 feeds three items by version). An empty list means the item has no epic yet.
- Items are reported in the order they appear, so keep it the same as the roadmap table.
- `prerequisite_releases` shows those releases (and their progress) next to the item.

## Use it as a Claude Code skill

```bash
./scripts/install-skill.sh          # macOS / Linux / Git Bash
./scripts/install-skill.ps1         # Windows PowerShell
```

This copies the skill to `~/.claude/skills/sprint-review-progress` and puts your `.env` at `~/.sprint-review.env` so it works from any folder. Then ask Claude things like *"build the sprint review report"* or *"گزارش اسپرینت ریویو را بساز"*.

## Project layout

```text
.
├── .env.example                          settings template (copy to .env, which is git-ignored)
├── skills/sprint-review-progress/
│   ├── SKILL.md                          instructions Claude follows
│   ├── mapping.json                      roadmap items → epics, prerequisites, translations
│   └── scripts/sprint_progress.py        the report generator
├── scripts/
│   ├── install-skill.sh                  install the skill (bash)
│   └── install-skill.ps1                 install the skill (PowerShell)
├── CHANGELOG.md
└── README.md
```

## Troubleshooting

| Message | Cause and fix |
|---|---|
| `Missing JIRA_BASE_URL and JIRA_PAT` | No `.env` found. Copy `.env.example` to `.env` and fill it in |
| `Jira answered HTTP 401` | Token wrong or expired. Create a new Personal Access Token |
| `Jira answered HTTP 404 … JIRA_BOARD_ID` | The board id or project key is wrong. `--check` shows what was used |
| `Jira has no field named "Story Points"` | Your field has another name. Set `JIRA_STORY_POINTS_FIELD` |
| A sprint tab is missing | Its name does not start with `SPRINT_PREFIX` or does not contain `SPRINT_QUARTER` |
| Bugs show no Story Points | The *Story Points* field is not enabled for the Bug issue type in Jira |
