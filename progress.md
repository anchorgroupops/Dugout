# Progress Log

- [2026-03-26] Task initialization.
- [2026-03-26] Plan defined in `task_plan.md`.
- [2026-03-26] PWA conversion audit — all features confirmed complete. Updated task_plan.md to reflect actual status.
- [2026-07-11] Fix GC verification-code email flood: reuse saved autopull session before forcing login; share one login across the team sweep (tools/autopull/session_manager.py, cli.py).
- [2026-07-11] Harden GC auth: emailed-2FA reader shared with daemon scrapers, global login-email budget, unified auth.json session store, per-stage cooldown recheck (SIGN-007).
- [2026-08-27] Add Eval section: tools/eval_engine.py (drill library + position-fit scoring blending preseason drill logs with last-season stats), /api/evals GET/POST, Evals dashboard tab, tests (34).
- [2026-09-02] Fix autopull false 'not authenticated' at /teams (run #146): auth check uses GC sign-in test IDs + jwt cookie and polls for the SPA to settle (SIGN-009).
- [2026-09-02] Site audit: lock nginx /data/ to dashboard JSON (SIGN-010), shared write token on mutating /api (SIGN-011), SSRF allow-list on music ingest, single CSP owner per response, single announcer repair loop, CORS always_send off, least-privilege CI, loopback dashboard port, latin-only fonts, SW controllerchange reload; merged 7 Dependabot PRs.
