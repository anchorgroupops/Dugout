# Progress Log

- [2026-03-26] Task initialization.
- [2026-03-26] Plan defined in `task_plan.md`.
- [2026-03-26] PWA conversion audit — all features confirmed complete. Updated task_plan.md to reflect actual status.
- [2026-07-11] Fix GC verification-code email flood: reuse saved autopull session before forcing login; share one login across the team sweep (tools/autopull/session_manager.py, cli.py).
- [2026-07-11] Harden GC auth: emailed-2FA reader shared with daemon scrapers, global login-email budget, unified auth.json session store, per-stage cooldown recheck (SIGN-007).
- [2026-08-27] Add Eval section: tools/eval_engine.py (drill library + position-fit scoring blending preseason drill logs with last-season stats), /api/evals GET/POST, Evals dashboard tab, tests (34).
- [2026-09-02] Fix autopull false 'not authenticated' at /teams (run #146): auth check uses GC sign-in test IDs + jwt cookie and polls for the SPA to settle (SIGN-009).
- [2026-09-02] Site audit: lock nginx /data/ to dashboard JSON (SIGN-010), shared write token on mutating /api (SIGN-011), SSRF allow-list on music ingest, single CSP owner per response, single announcer repair loop, CORS always_send off, least-privilege CI, loopback dashboard port, latin-only fonts, SW controllerchange reload; merged 7 Dependabot PRs.
- [2026-09-15] Announcer Halo-quality pass: ElevenLabs gets real <break/> pauses, Stadium Wrap v2 (dynamics kept, true stereo PA tail, -16 LUFS loudnorm, 192 kbps), clips from the old chain flagged for re-render, versioned voice samples; tests (+11).
- [2026-09-16] Announcer v3: Stadium Wrap stereo actually survives the Pi's ffmpeg 4.4 (amix dropped for a two-leg join, SIGN-012); no number call for players without a jersey number; one-letter GameChanger surnames no longer read out as letters; CI installs ffmpeg so the audio contract runs.
- [2026-09-28] Harden pass: fixed Windows-path test assertion in test_aggregate_team_stats (platform-dependent str(Path) comparison); fixed uncaught ValueError 500 on non-numeric/empty ?limit= in /api/announcer/songs/search and /api/announcer/catalog/search via _safe_int (SIGN-014); route-fuzzed sync_daemon.py GET/path-param surface, no path traversal or other 500s found.
- [2026-09-28] GC autopull silent-failure fixes (SIGN-015): header-only exports now quarantine instead of wiping team.json, empty rosters never written, daemon stops re-stamping the Spring CSV as fresh, /api/health reports gc_autopull, session reuse trusts /me/* status and re-saves refreshed tokens; tests (+18).
