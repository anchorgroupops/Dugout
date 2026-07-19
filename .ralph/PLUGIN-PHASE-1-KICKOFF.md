# Phase 1 Kickoff — `anchor-loop-library` Cowork Plugin

**Purpose:** Self-contained brief. Hand this to a fresh-context Claude session and the plugin gets built end-to-end without a re-explain.

**Scope:** Phase 1 only — local plugin scaffold + `init-loop` skill + smoke test. Distribution + `audit-loop` are Phases 2/3.

**Estimated context budget:** ~40% of a Sonnet/Opus session. Plan for one continuous sitting; do not try to chunk across two sessions.

---

## Session opening — paste this prompt into the new session

```
Build the `anchor-loop-library` Cowork plugin. Brief is at:
  H:\Projects\PCLL\Dugout\.ralph\PLUGIN-PHASE-1-KICKOFF.md
  (or in Cowork: /sessions/<id>/mnt/Dugout/.ralph/PLUGIN-PHASE-1-KICKOFF.md)

Read that brief, the source manifest it links, and the
PLUGIN-ROADMAP.md sibling. Then invoke the
`cowork-plugin-management:create-cowork-plugin` skill and execute
Phase 1 to completion. Do not ask me clarifying questions unless you
hit an actual blocker — defaults in the brief are authoritative.
```

That prompt is intentionally terse: the brief carries the load.

---

## Acceptance criteria (Phase 1 done = all of these pass)

1. `anchor-loop-library/` directory exists with the layout from PLUGIN-ROADMAP.md
2. `plugin.json` declares: name, version `0.1.0`, owner `anchorgroupops`, two skills, one slash command
3. `skills/init-loop/SKILL.md` is invokable and renders inputs via AskUserQuestion (one question at a time, ≤4 options each)
4. All 7 templates in `templates/` exist with `{{PLACEHOLDER}}` substitution markers — diffed against current Dugout files for parity
5. All 3 n8n workflow JSONs in `n8n-workflows/` exported with placeholders for project slug, repo, chat ID, GitHub PAT, n8n API key
6. Smoke test: scaffold a throwaway `dugout-test/` directory using the new plugin → all 6 artefacts emit → diff vs original Dugout shows only placeholder→value substitutions
7. README.md at plugin root explains install, usage, troubleshooting
8. `.plugin` archive built (or skipped with note if `cowork-plugin-management:create-cowork-plugin` skill defers archiving to Phase 2)

---

## Source manifest — files to template from

**From `H:\Projects\PCLL\Dugout\` (this repo):**

| Source file | Becomes template | Placeholders to inject |
|---|---|---|
| `prd.md` | `templates/prd.md.tpl` | `{{PROJECT_SLUG}}`, `{{STACK_PROFILE}}` (Next.js \| Astro \| Pi-Python \| n8n-only) |
| `PROMPT.md` | `templates/PROMPT.md.tpl` | `{{PROJECT_SLUG}}` |
| `.ralph/guardrails.md` | `templates/guardrails.md.tpl` | `{{PROJECT_SLUG}}`, brand palette tokens |
| `scripts/ralph-watchdog.ps1` | `templates/ralph-watchdog.ps1.tpl` | `{{PROJECT_ROOT_WIN}}`, `{{ITERATIONS}}`, `{{N8N_BASE_URL}}`, `{{WEBHOOK_PATH}}` |
| `scripts/ralph-watchdog.sh` | `templates/ralph-watchdog.sh.tpl` | `{{PROJECT_ROOT_NIX}}`, `{{ITERATIONS}}`, `{{N8N_BASE_URL}}`, `{{WEBHOOK_PATH}}` |
| `scripts/ralph-command-poller.ps1` | `templates/ralph-command-poller.ps1.tpl` | `{{PROJECT_ROOT_WIN}}`, `{{REPO}}` |
| `scripts/ralph-command-poller.sh` | `templates/ralph-command-poller.sh.tpl` | `{{PROJECT_ROOT_NIX}}`, `{{REPO}}` |

**From n8n (Pi, https://n8n.joelycannoli.com) — export via `n8n_get_workflow`:**

| Workflow ID | Becomes | Placeholders to inject |
|---|---|---|
| `h1T0OtI2xnJqEfVh` | `n8n-workflows/watchdog-router.json` | `{{PROJECT_NAME}}`, `{{WEBHOOK_PATH}}`, `{{TELEGRAM_CHAT_ID}}` |
| `jodsyjVl6HeTZjjI` | `n8n-workflows/telegram-commands.json` | `{{PROJECT_NAME}}`, `{{REPO}}`, `{{TELEGRAM_CHAT_ID}}`, `{{N8N_API_KEY}}`, `{{GITHUB_PAT}}`, command prefix `{{CMD_PREFIX}}` (e.g. `dugout`) |
| `49HKHZiG82sg0eRJ` | `n8n-workflows/drift-watcher.json` | `{{PROJECT_NAME}}`, `{{REPO}}`, `{{TELEGRAM_CHAT_ID}}`, `{{GITHUB_PAT}}` |

**Important:** strip the `id`, `versionId`, `meta.instanceId`, and credential bindings from each exported JSON before templating — they cause re-import collisions.

---

## init-loop skill spec

```yaml
name: init-loop
trigger_words:
  - "set up loop"
  - "wire up watchdog"
  - "init ralph for"
  - "install anchor loop"
  - "scaffold autonomous loop"

questions_in_order:
  1. project_slug:
     type: text
     example: "dugout"
  2. github_repo:
     type: text
     example: "anchorgroupops/dugout"
  3. project_root_pc:
     type: text
     example: "H:\\Projects\\PCLL\\Dugout"
  4. stack_profile:
     type: choice
     options: ["Next.js", "Astro", "Pi-native Python", "n8n-only"]
  5. telegram_chat_id:
     type: text
     default: "DORI" (resolves to known DORI chat ID stored in plugin config)
  6. iterations:
     type: choice
     options: ["5", "10", "15", "20"]
     default: "10"

execution_steps:
  - render all 7 templates with substitutions → write to project_root
  - import 3 n8n workflows via mcp__n8n__n8n_create_workflow → capture new IDs
  - rewrite scripts to use new webhook path (derived from project_slug)
  - emit pasteable schtasks (Win) OR crontab (Mac) commands based on host detection
  - print green-tick checklist with ✅/❌ per artefact
  - save `.ralph/INSTALL-LOG.md` to project root with timestamps and IDs

guardrails:
  - never overwrite existing files without explicit "force" arg
  - if any of the 3 source workflows are missing from n8n, abort with clear error
  - validate gh CLI auth before scheduling
```

---

## Pre-session checklist (do before kicking off)

- [ ] Both PCs running, n8n on Pi healthy (`mcp__n8n__n8n_health_check`)
- [ ] `cowork-plugin-management:create-cowork-plugin` skill is loaded in available skills
- [ ] All 3 source n8n workflows still exist with the IDs above (drift removal would block Phase 1)
- [ ] Dugout repo working tree clean — fresh session may want to git diff against templates
- [ ] You have ~90 min uninterrupted (skill execution + smoke test)

---

## Out of scope for Phase 1 (do NOT let the fresh session scope-creep)

- Audit-loop skill (Phase 3)
- Multi-tenant Telegram bot (forever-deferred — DORI is the surface)
- Plugin marketplace publishing (Phase 2)
- Migration of existing Dugout setup to consume the plugin (Phase 2 — Dugout stays as reference)
- CI integration / GitHub Actions packaging
- Telemetry

---

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| n8n workflow JSON shape changes between export & import | Test re-import into a `_test_` project on Pi before declaring done |
| Template substitution misses a path (Windows backslash escaping) | Smoke test specifically uses a path with backslashes |
| `gh` CLI version skew between PC/Mac changes flag names | Pin to features available in `gh >= 2.40` and document in plugin README |
| Cowork session ID changes the absolute path before plugin emits | Plugin emits with relative paths from project_root, never session paths |

---

## Success signal

End-of-session message from fresh Claude should look like:

> ✅ `anchor-loop-library` v0.1.0 scaffolded at `H:\Projects\anchor-loop-library\`
> ✅ Smoke test in `dugout-test/` produced 6 artefacts, diff vs Dugout source = placeholders only
> ✅ 3 n8n workflows imported as `_test_` copies (IDs: …, …, …) — review and delete when ready
> ✅ Pasteable schtasks block ready below

If you see that, Phase 1 is done. Phase 2 (publish to private Anchor marketplace) becomes the next session's plan.

---

_Drafted 2026-04-18 from current Dugout reference implementation. Review before kicking off — 24h freshness is recommended since n8n workflows can drift._
