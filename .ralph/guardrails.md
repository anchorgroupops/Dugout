# Ralph Guardrails — Dugout Portal (Full Send Remediation Loop)

## Base signs (non-negotiable)

**SIGN-001 — One phase per iteration.**
The agent completes exactly one `/full-send` phase (one prd.md task) and commits before the iteration ends. No skipping ahead, no bundling phases. Fresh context every iteration is the whole point — use it.

**SIGN-002 — Verify ALL tasks before COMPLETE.**
Before outputting `<promise>COMPLETE</promise>`, re-read prd.md from disk and confirm every `"passes": true`. Do not trust memory. Also confirm `git status` has no uncommitted changes.

**SIGN-003 — activity.md first, every time.**
Read activity.md at the start of every iteration before deciding what to do. It is the only cross-iteration memory.

---

## Project-specific signs (Dugout / Anchor Group)

**SIGN-004 — GitOps: human approves every push.**
Never run `git push`. Phase 6 commits locally; the human pushes after review. If prd.md task 7 is reached, commit and output `<promise>COMPLETE</promise>` — do not push.

**SIGN-005 — Secrets stay out of git.**
Before every commit, run `git status` and scan staged files for `.env`, `.env.local`, `.env.production`, `config.js`, or any file matching `*secret*`/`*token*`/`*key*`. If present, unstage and halt.

**SIGN-006 — n8n webhooks must degrade gracefully.**
Any change to `src/lib/n8n.ts` or API routes calling n8n must include a fallback path. The Pi 5 is production infra and can be offline (network hiccup, Cloudflare Tunnel down). The UI must render a fallback state, not crash.

**SIGN-007 — Brand palette only.**
UI changes use only #157676 (teal), #89ced1 (light teal), #ffffff, and neutral greyscale derived from Tailwind's `slate` scale. No introducing pinks, yellows, or purples without explicit human approval.

**SIGN-008 — Self-heal cap at 3 attempts.**
If an error recurs after 3 distinct fix attempts, roll back (`git stash pop` from Phase 0 snapshot), log the failure pattern, and halt the loop. Do not loop infinitely on the same break.

**SIGN-009 — Learning log is append-only.**
Never rewrite or truncate `.full-send/learning-log.json`. Always append. If the file is malformed, preserve the old one as `.learning-log.bak-{timestamp}.json` before starting fresh.

**SIGN-010 — Conventional commits only.**
Format: `full-send phase <N>: <imperative summary>`. No emoji in commit messages. No co-authored-by trailers unless the human requested it.

**SIGN-011 — No destructive git.**
Never run `git reset --hard`, `git push --force`, `git checkout .`, or `rm -rf`. These can destroy the user's work.

**SIGN-012 — Supabase RLS respected.**
Any Supabase query must assume Row-Level Security is enforced. Do not bypass RLS with service-role keys in client code.
