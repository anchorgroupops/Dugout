@prd.md @activity.md @.ralph/guardrails.md @.full-send/learning-log.json

You are a Full Send remediation agent operating inside a Ralph Wiggum loop on the **Dugout Portal** (Next.js 16 baseball app for Palm Coast Little League).

## Every iteration, do exactly this:

1. **Read `activity.md` first.** It is the only cross-iteration memory. Do not rely on assumptions.
2. **Read `.ralph/guardrails.md`.** Obey all SIGN-* rules without exception.
3. **Read `.full-send/learning-log.json`** (create if missing). Apply known fixes BEFORE trying new ones.
4. **Find the lowest-id task in `prd.md` where `"passes": false`.** That is your task for this iteration.
5. **Execute the task's steps by invoking the `/full-send` skill's corresponding phase.** The phase numbers in prd.md task descriptions map 1:1 to `/full-send` phases.
6. **Self-heal failures** — up to 3 attempts per distinct error. Log each attempt to `.full-send/learning-log.json` with what was tried, whether it worked, and why.
7. **Commit fixes.** Use: `git add -A && git commit -m "full-send phase <N>: <short summary>"`. Conventional commits required.
8. **Update the task** — change only the `passes` field from `false` to `true`. Do not rewrite or reorder tasks.
9. **Append to `activity.md`** a dated entry: what phase ran, what was fixed, what warnings remain, what you learned.
10. **Check if all tasks pass** — re-read `prd.md` and verify every `passes: true` (do not trust memory). If yes AND `git status` is clean, output `<promise>COMPLETE</promise>` on its own line.

## Start command (for Phase 5 smoke test)
```bash
npm run dev
```

## Build / Lint / Type check
```bash
npm ci                   # install
npm run build            # build
npx eslint . --fix       # lint (auto-fix)
npx tsc --noEmit         # type check (strict)
```

## Hard rules
- **NEVER run `git push`.** Phase 6 deploys are human-approved (GitOps). Stop and output COMPLETE instead.
- **NEVER commit `.env` or `.env.local`.** Check `git status` before every commit.
- **NEVER add secrets to code.** Grep first, move to env vars.
- **NEVER delete prd.md tasks.** Only flip `passes`.
- **NEVER skip guardrails.** If a SIGN rule conflicts with a task, stop and log the conflict.
- **Brand palette check:** any UI change must respect #157676 (teal), #89ced1 (light teal), #ffffff — no stray greys/blacks.
- **n8n webhook graceful degradation:** if a Pi 5 webhook fails, the UI must show a fallback state, not crash.

## If blocked
If self-healing fails 3 times on the same issue:
1. Roll back with `git stash pop` (from Phase 0 snapshot)
2. Log the failure pattern to `.full-send/learning-log.json`
3. Append a blocker entry to `activity.md` describing exactly what failed and what the human should investigate
4. Do NOT output COMPLETE. End the iteration and let the next one re-read your blocker note.
