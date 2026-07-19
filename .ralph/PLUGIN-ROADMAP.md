# Anchor Loop Library — Cowork Plugin Roadmap

**Status:** Design — not yet packaged.
**Owner:** Joel (anchorgroupops)
**Goal:** Take the Dugout watchdog + command queue + drift watcher pattern and make it a one-command install for any future Anchor Group project (FUB, Pi-native utilities, n8n satellites).

---

## Why a plugin?

The Dugout setup is now ~6 moving parts:

1. `ralph.sh` + `prd.md` + `PROMPT.md` + `.ralph/guardrails.md`
2. Watchdog wrapper (`scripts/ralph-watchdog.{ps1,sh}`)
3. n8n router workflow (`Dugout Ralph Watchdog Router`)
4. Telegram commands workflow (`Dugout Telegram Commands`)
5. Drift watcher workflow (`Dugout Drift Watcher`)
6. Command poller (`scripts/ralph-command-poller.{ps1,sh}`)

Standing this up by hand for a second project would take 40+ minutes and is error-prone. A Cowork plugin reduces it to:

```bash
claude plugin install anchor-loop-library
claude /init-loop --project=<name> --repo=<github/repo>
```

…and emits all six artefacts pre-templated for the new project.

---

## Plugin shape (proposed)

```
anchor-loop-library/
├── plugin.json                       # metadata, version, owner
├── skills/
│   ├── init-loop/                    # primary scaffolder
│   │   └── SKILL.md
│   ├── add-watchdog/                 # standalone watchdog only
│   │   └── SKILL.md
│   └── add-telegram-commands/        # standalone command surface
│       └── SKILL.md
├── commands/
│   ├── init-loop.md                  # /init-loop slash command
│   └── audit-loop.md                 # /audit-loop — health-check existing setup
├── templates/
│   ├── prd.md.tpl
│   ├── PROMPT.md.tpl
│   ├── guardrails.md.tpl
│   ├── ralph-watchdog.ps1.tpl
│   ├── ralph-watchdog.sh.tpl
│   ├── ralph-command-poller.ps1.tpl
│   └── ralph-command-poller.sh.tpl
├── n8n-workflows/
│   ├── watchdog-router.json          # exported, with {{PROJECT}} placeholders
│   ├── telegram-commands.json
│   └── drift-watcher.json
└── README.md
```

---

## Skill: `init-loop`

**Trigger words:** "set up loop", "wire up watchdog", "init ralph for <project>", "install anchor loop"

**Inputs (asked via AskUserQuestion):**

- Project name (slug, e.g. `dugout`)
- GitHub repo (`owner/repo`)
- Project root path on PC
- Stack profile (Next.js / Astro / Pi-native Python / n8n-only)
- Telegram chat ID (default to DORI)
- n8n base URL (default `https://n8n.joelycannoli.com`)

**Outputs:**

- All 6 artefacts written, populated, with the right paths
- 3 n8n workflows imported via `n8n_create_workflow` MCP, IDs captured
- Pasteable schtasks (Windows) or crontab (mac) lines
- Green-tick checklist

---

## Skill: `audit-loop`

Health-check an existing loop. Verifies:

- `ralph.sh` exists + executable
- All required scripts present
- n8n workflows still active (queries `n8n_list_workflows`)
- Webhook URLs reachable (HEAD request)
- Last watchdog run was within 25 hours
- gh CLI authenticated
- GitHub PAT secret set in n8n env

Outputs a green/red dashboard.

---

## Templating strategy

Use simple `{{PLACEHOLDER}}` substitution. No Handlebars dependency — keeps the plugin pure-bash compatible. Placeholders:

| Placeholder | Source |
|---|---|
| `{{PROJECT_SLUG}}` | user input |
| `{{PROJECT_ROOT_WIN}}` / `{{PROJECT_ROOT_NIX}}` | user input |
| `{{REPO}}` | user input |
| `{{N8N_BASE_URL}}` | user input or default |
| `{{WEBHOOK_PATH}}` | derived from slug |
| `{{TELEGRAM_CHAT_ID}}` | user input or DORI |
| `{{ITERATIONS}}` | default 10, overridable |

---

## Phasing

**Phase 1 — Local plugin (1 session)**
- Carve `templates/` from current Dugout files (already in this repo)
- Author `skills/init-loop/SKILL.md`
- Test by re-scaffolding a throwaway `dugout-test/` directory
- Smoke-test n8n imports

**Phase 2 — Distribution (later)**
- Wrap into `.plugin` archive via `cowork-plugin-management:create-cowork-plugin` skill
- Publish to private Anchor marketplace
- Doc on Notion: "How to install Anchor Loop"

**Phase 3 — Polish (later)**
- `audit-loop` skill
- Auto-detect existing setups and offer upgrade
- Telemetry — opt-in ping of plugin usage to Pi for trend tracking

---

## What's NOT in scope

- Multi-tenant Telegram bot (each project still uses DORI as the surface)
- n8n credential rotation (still manual via UI)
- Generic CI runner — this is Ralph + watchdog only, not a Jenkins replacement
- Migration of existing Dugout setup — Dugout stays as the reference implementation

---

## Cross-reference

- Source-of-truth artefacts: this repo, all under `scripts/`, `.ralph/`, repo root.
- n8n workflows used as templates:
  - `h1T0OtI2xnJqEfVh` — Dugout Ralph Watchdog Router
  - `jodsyjVl6HeTZjjI` — Dugout Telegram Commands
  - `49HKHZiG82sg0eRJ` — Dugout Drift Watcher
- Existing plugin skills to lean on:
  - `cowork-plugin-management:create-cowork-plugin` (packaging)
  - `cowork-plugin-management:cowork-plugin-customizer` (per-org tweaks)

---

_Roadmap drafted by full-send/ralph extension session 2026-04-18. Ship Phase 1 in a dedicated future session — multi-step plugin packaging needs its own context budget._
