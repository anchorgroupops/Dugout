---
description: Full Quality Control audit loop for the Sharks Dashboard project
---

# QC Loop — Sharks Dashboard

// turbo-all

## 1. Lint Check
```bash
cd h:\Repos\Personal\Softball\client && npx eslint .
```
Record all warnings and errors. Fix any errors before proceeding.

## 2. Production Build
```bash
cd h:\Repos\Personal\Softball\client && npm run build
```
Build must exit 0 with no errors. Warnings are acceptable but should be noted.

## 3. Code Review Scan
Manually review the following files for dead code, unused imports, accessibility issues, and inconsistencies:
- `client/src/App.jsx` — Main app shell, nav, state management
- `client/src/index.css` — Global styles, design tokens, responsive rules
- All components in `client/src/components/`
- `client/src/utils/` — Utility functions

Check for:
- [ ] Unused imports or variables
- [ ] Dead code / unreachable branches
- [ ] Accessibility issues (missing aria labels, touch targets < 44px)
- [ ] Inconsistent styling patterns
- [ ] Hardcoded values that should be CSS variables
- [ ] Missing error boundaries or error handling

## 4. Visual QC (Browser)
Open `https://sharks.joelycannoli.com/` in the browser and verify:
- [ ] Page loads without console errors
- [ ] Navigation works (all tabs)
- [ ] Mobile layout renders correctly (resize to 375px width)
- [ ] Desktop layout renders correctly
- [ ] Buttons, dots, and interactive elements are visible and functional
- [ ] Glassmorphism and animations render smoothly

## 5. Docker / Deployment Audit
Review:
- `docker-compose.sharks.yml` — Security, healthchecks, network isolation
- `client/Dockerfile` — Build stages, layer caching
- `client/nginx.conf` — Proxy rules, caching headers, security headers
- `.github/workflows/deploy.yml` — CI/CD pipeline correctness
- `scripts/deploy.sh` — Deployment script safety

## 6. Report
Create a QC report artifact at `walkthrough.md` summarizing:
- Lint results (pass/fail, error count)
- Build results (pass/fail)
- Code review findings (categorized by severity)
- Visual QC results
- Deployment audit findings
- Recommended fixes (ordered by priority)
