#!/usr/bin/env node
/**
 * Undefined-JSX-component checker.
 *
 * Why this exists
 * ---------------
 * `Scoreboard.jsx` shipped four JSX tags — `<SprayChart>`, `<InningDiamond>`,
 * `<BatterCard>` and `<CollapsibleSection>` — that were never defined or
 * imported anywhere. Every one of them is a `ReferenceError` the moment the
 * branch containing it renders, which meant the Live tab (the app's default
 * view, and the one used in the dugout) white-screened into the error boundary
 * during an actual game.
 *
 * Nothing in the existing toolchain caught it:
 *   - ESLint's `no-undef` does not create references for JSXIdentifier nodes,
 *     so a bare `<Foo />` is invisible to it. That is precisely why
 *     `eslint-plugin-react` ships a separate `react/jsx-no-undef` rule, and
 *     this project does not depend on that plugin.
 *   - Rollup and esbuild treat unresolved bare identifiers as globals, so the
 *     production build succeeds happily.
 *
 * This script closes that gap with no new dependencies: it scans each JSX file
 * for capitalised component tags and asserts each one is either imported or
 * declared in the same file. It is deliberately conservative — it only reports
 * a name when it can find no binding for it at all.
 *
 * Run: node scripts/check_jsx_refs.mjs
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const SRC = join(ROOT, 'src');

/** Tags that look like components but are resolved by the runtime, not by a binding. */
const ALWAYS_DEFINED = new Set([
  // React.Fragment shorthand shows up as an empty tag and never matches anyway,
  // but namespaced members like <React.Suspense> are handled by the dot check.
]);

/** Recursively collect .jsx / .js files under src/. */
function walk(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...walk(full));
    } else if (/\.(jsx|js)$/.test(entry)) {
      out.push(full);
    }
  }
  return out;
}

/**
 * Strip comments and string/template literals so their contents cannot be
 * mistaken for JSX. Crude but sufficient: we only need the identifier
 * positions, not a faithful parse.
 */
function stripNoise(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/(^|[^:])\/\/[^\n]*/g, '$1 ')
    .replace(/`(?:\\[\s\S]|[^`\\])*`/g, '``')
    .replace(/'(?:\\[\s\S]|[^'\\\n])*'/g, "''")
    .replace(/"(?:\\[\s\S]|[^"\\\n])*"/g, '""');
}

/** Names bound in this module: imports, declarations, and function params-ish. */
function collectBindings(src) {
  const names = new Set();
  const add = (s) => { if (s) names.add(s.trim()); };

  // import Default, { A, B as C } from '...'   /   import * as NS from '...'
  for (const m of src.matchAll(/import\s+([\s\S]*?)\s+from\s+['"]/g)) {
    const clause = m[1];
    for (const part of clause.split(',')) {
      const p = part.trim();
      if (!p) continue;
      if (p.startsWith('*')) {
        add(p.replace(/\*\s*as\s*/, ''));
      } else if (p.startsWith('{') || p.endsWith('}')) {
        for (const inner of p.replace(/[{}]/g, '').split(',')) {
          const bits = inner.split(/\s+as\s+/);
          add(bits[bits.length - 1]);
        }
      } else {
        add(p);
      }
    }
  }

  // const/let/var Foo = ...   and   function Foo(...)   and   class Foo
  for (const m of src.matchAll(/\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)/g)) add(m[1]);
  for (const m of src.matchAll(/\bfunction\s+([A-Za-z_$][\w$]*)/g)) add(m[1]);
  for (const m of src.matchAll(/\bclass\s+([A-Za-z_$][\w$]*)/g)) add(m[1]);
  // Destructured bindings: const { A, B } = ...
  for (const m of src.matchAll(/\b(?:const|let|var)\s*\{([^}]*)\}\s*=/g)) {
    for (const inner of m[1].split(',')) {
      const bits = inner.split(/[:=]/);
      add(bits[bits.length > 1 ? 1 : 0]);
    }
  }

  return names;
}

/** Capitalised JSX tags used in this module. */
function collectJsxTags(src) {
  const tags = new Set();
  for (const m of src.matchAll(/<([A-Z][\w$]*)(?:\.[\w$]+)*[\s/>]/g)) {
    // A dotted tag such as <React.Suspense> only needs its root object bound.
    tags.add(m[1]);
  }
  return tags;
}

let failures = 0;
const files = walk(SRC).sort();

for (const file of files) {
  const raw = readFileSync(file, 'utf8');
  const src = stripNoise(raw);
  const bound = collectBindings(src);
  const used = collectJsxTags(src);

  for (const tag of used) {
    if (bound.has(tag) || ALWAYS_DEFINED.has(tag)) continue;
    // Report with the first line the tag appears on, for a clickable location.
    const lineNo = raw.split('\n').findIndex(l => new RegExp(`<${tag}[\\s/>]`).test(l)) + 1;
    console.error(
      `${relative(ROOT, file)}:${lineNo || 1}  <${tag}> is used but never imported or defined`
    );
    failures += 1;
  }
}

if (failures > 0) {
  console.error(`\n${failures} undefined JSX component reference(s). Each is a ReferenceError at render.`);
  process.exit(1);
}

console.log(`check_jsx_refs: ${files.length} files scanned, no undefined JSX components.`);
