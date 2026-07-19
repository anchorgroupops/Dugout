# Dugout Portal — Full Send Remediation PRD

## Overview
Autonomous Ralph loop that runs the `/full-send` pipeline iteratively against the Dugout Portal (Next.js 16 baseball app for Palm Coast Little League). Each iteration executes one phase of Full Send, fixes what's fixable, logs outcomes, and commits. Loop exits when all phases pass clean (no blocking issues, no new changes required) and `git status` reports a clean tree.

This is a **remediation loop**, not a feature-build loop. The success signal is "the project is production-ready and shippable," not "N features were added."

## Tech Stack
- **Framework:** Next.js 16 (App Router, TypeScript, Tailwind CSS)
- **Hosting:** Vercel (team: anchorgroupops)
- **Backend:** n8n webhooks on Pi 5 via HTTP POST (`src/lib/n8n.ts`)
- **Database:** Supabase — PCLL Field Scheduler (us-east-1)
- **Repo:** `anchorgroupops/Dugout` (GitHub)
- **Brand palette:** #157676 / #89ced1 / #ffffff

## Loop Semantics
- One `/full-send` **phase** per iteration (not the whole pipeline)
- After each phase: log to `activity.md`, commit fixes, flip `passes: true`
- `/full-send` Phase 6 (Deploy) is gated behind **human approval** — the agent STOPS at the push step and waits for the user to confirm on the next manual run
- Phase 0 (Recon) and Phase 8 (Learn) run implicitly at the start and end

## Task List

```json
[
  {
    "id": 1,
    "category": "setup",
    "description": "Phase 0 — Recon: identify stack, load .full-send/learning-log.json, snapshot state",
    "steps": [
      "Auto-detect stack from package.json",
      "Verify deploy target (vercel.json or .github/workflows)",
      "Read .full-send/learning-log.json (create if missing)",
      "git stash --include-untracked -m \"full-send-backup-$(date +%s)\""
    ],
    "passes": false
  },
  {
    "id": 2,
    "category": "testing",
    "description": "Phase 1 — Lint & Build: fix all build errors, auto-fix lint, report remaining warnings",
    "steps": [
      "Run `npm ci` cleanly (apply --legacy-peer-deps if learning log says so)",
      "Run `npm run build` — fix all errors, do not just report",
      "Run `npx eslint . --fix` (or biome/ruff equivalent)",
      "Self-heal build failures: up to 3 attempts per error",
      "Append fixes to .full-send/learning-log.json"
    ],
    "passes": false
  },
  {
    "id": 3,
    "category": "feature",
    "description": "Phase 2 — Frontend Audit: accessibility, console/runtime, performance, error resilience, SEO/meta",
    "steps": [
      "Scan for missing alt tags, ARIA attributes, form labels — fix",
      "Verify semantic HTML (main, nav, header — no div soup)",
      "Check brand colour contrast (#157676 / #89ced1 / #ffffff) — WCAG AA",
      "Remove console.log/console.error from production paths (or guard with NODE_ENV)",
      "Replace hardcoded localhost URLs with env vars",
      "Verify ErrorBoundary present, loading states, 404 route",
      "Confirm title/meta/OG/favicon"
    ],
    "passes": false
  },
  {
    "id": 4,
    "category": "feature",
    "description": "Phase 3 — Backend Audit: secrets, API hardening, auth, observability",
    "steps": [
      "Grep source for API keys/tokens — move to .env (gitignored)",
      "Confirm .env.example documents all required vars",
      "Audit API routes for try/catch, input validation, CORS, rate limiting",
      "Verify auth checks on protected routes (Supabase session)",
      "Ensure /api/health endpoint exists and returns 200",
      "Confirm n8n webhook errors degrade gracefully (per Pi constraint)"
    ],
    "passes": false
  },
  {
    "id": 5,
    "category": "integration",
    "description": "Phase 4 — Harden: deps, security headers, code hygiene, infra",
    "steps": [
      "`npm audit` — fix critical/high (skip breaking majors)",
      "Remove unused dependencies from package.json",
      "Add/verify CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, HSTS (vercel.json headers)",
      "Remove dead code, commented blocks, TODO hacks",
      "Verify TypeScript strict: true",
      "Confirm .gitignore covers node_modules, .env*, .DS_Store, .next"
    ],
    "passes": false
  },
  {
    "id": 6,
    "category": "testing",
    "description": "Phase 5 — Test: run suite or trace critical path, fix failures",
    "steps": [
      "If test suite exists: run, fix failures (update stale snapshots)",
      "If no suite: manually trace critical paths (coach loads schedule, views roster, views scores)",
      "Verify happy path renders data from n8n/Supabase",
      "Confirm error states render gracefully (n8n down, Supabase timeout)"
    ],
    "passes": false
  },
  {
    "id": 7,
    "category": "setup",
    "description": "Phase 6 — Deploy (HITL gate): stage commit, STOP before push to main",
    "steps": [
      "git add -A",
      "git commit -m \"FULL SEND: [summary]\"",
      "STOP — mark task passes:true and output <promise>COMPLETE</promise> so the human can review and push",
      "Do NOT run `git push` — GitOps rule requires human approval"
    ],
    "passes": false
  },
  {
    "id": 8,
    "category": "testing",
    "description": "Phase 7 — Post-Deploy Verify (manual, deferred): documented for human after push",
    "steps": [
      "Write verification checklist to .full-send/verify-checklist.md (curl live URL, check mixed content, verify n8n webhook reachability, confirm Supabase RLS, check for console errors in prod)",
      "This task auto-passes once the checklist file is written — the human runs it after push"
    ],
    "passes": false
  }
]
```

## Completion Criteria
All tasks marked `"passes": true` AND `git status` is clean on all non-staged paths (the only staged change allowed is the Full Send commit itself). Agent outputs `<promise>COMPLETE</promise>` on the final iteration.

## Failure Escalation
If any phase fails self-healing after 3 attempts:
1. Roll back to Phase 0 snapshot (`git stash pop`)
2. Append failure pattern to `.full-send/learning-log.json`
3. Set the offending task's `passes` to `"blocked"` (custom state)
4. Output the blocker reason and stop — do not claim COMPLETE

## Project Quirks (seed — will grow via learning log)
- Next.js 16 App Router (not Pages Router)
- n8n webhooks must degrade gracefully if Pi is unreachable
- Brand contrast check: #157676 teal on white is the primary pair
- GitOps rule: no `git push origin main` without human approval
