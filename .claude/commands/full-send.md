---
description: Full QC, harden, heal, improve, commit, push, and deploy — the everything button.
---

# Full Send — Sharks Dashboard

Run **every quality gate** in sequence below. Fix any issues you find before
moving to the next phase. At the end, commit, push, and trigger deploy.

---

## Phase 1: Lint & Build

1. **ESLint** — `cd client && npx eslint .`
   - Auto-fix what you can (`--fix`), manually fix the rest.
   - Zero errors required before moving on. Warnings are OK but note them.

2. **Production Build** — `cd client && VITE_SKIP_DATA_SYNC=1 npm run build`
   - Must exit 0.

3. **Python Smoke Tests** — run the same checks CI does:
   ```
   cd tools
   python -c "from stats_normalizer import safe_float; print('OK')"
   python -c "from swot_analyzer import compute_derived_stats; print('OK')"
   python -c "from lineup_optimizer import compute_batting_score; print('OK')"
   python -c "import py_compile; py_compile.compile('sync_daemon.py', doraise=True); print('OK')"
   ```
   - Fix any import or syntax errors you find.

## Phase 2: Code Review & Self-Heal

Scan these files for dead code, unused imports, unreachable branches, and
obvious bugs. **Fix** anything you find — don't just report it.

- `client/src/App.jsx`
- All components in `client/src/components/`
- `client/src/utils/` (if present)
- `tools/sync_daemon.py` (syntax-level only — it's large)

Checks:
- [ ] Remove unused imports and variables
- [ ] Remove dead / unreachable code
- [ ] Fix any console errors visible in the source
- [ ] Ensure no hardcoded secrets or credentials

## Phase 3: Harden

Review for security issues across the stack:

1. **Frontend** — XSS vectors, unsafe `dangerouslySetInnerHTML`, open redirects.
2. **Backend / API** — injection risks in `sync_daemon.py` routes, missing input validation.
3. **Docker** — verify `docker-compose.sharks.yml` still has:
   `read_only`, `no-new-privileges`, `cap_drop: ALL`, `mem_limit`, `pids_limit`.
4. **Nginx** — confirm `client/nginx.conf` has security headers
   (X-Content-Type-Options, X-Frame-Options, CSP, etc.).
5. **CI/CD** — verify GitHub Actions use pinned SHA commits (not floating tags).

Fix anything you find. If a fix is risky, flag it and move on.

## Phase 4: Self-Improve

Look for **low-risk, high-impact** improvements only:

- Accessibility: missing `aria-labels`, touch targets < 44px, color contrast.
- Performance: unnecessary re-renders, missing `React.memo` / `useMemo` where it matters.
- CSS: hardcoded values that should be design tokens / CSS variables.
- Python: any obviously inefficient patterns in hot-path tools.

Apply fixes inline. Do **not** refactor architecture or change APIs.

## Phase 5: Commit & Push

1. Stage all changed files (exclude `.env`, credentials, data files).
2. Write a concise commit message summarizing what was fixed/improved.
3. Push to the current branch with `git push -u origin <current-branch>`.
4. If push fails due to network, retry up to 4 times (2s, 4s, 8s, 16s backoff).

## Phase 6: Deploy Gate

After push, CI runs automatically (lint, build, python-check, Docker build).
- Confirm CI passed by checking the workflow status.
- If CI fails, diagnose and fix, then re-commit and push.
- Once CI is green, deployment happens automatically via Watchtower + GHCR.

Report a final summary: what was found, what was fixed, and current deploy status.
