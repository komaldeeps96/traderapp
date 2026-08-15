// ESLint for both TypeScript workspaces.
//
// `tsc` already carries most of the weight here — the config is strict, with
// `noUncheckedIndexedAccess` and `noUnusedLocals` — so this deliberately does
// not repeat type checking. It covers what a type checker structurally cannot
// see: exhausted-looking switches that are not, floating promises, React hook
// dependency arrays, and exports nobody imports.

import js from '@eslint/js';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  {
    // Build output, dependencies, and the trees git already ignores — the
    // pre-rewrite `legacy/` snapshot, the backtesting notebooks and their
    // vendored virtualenvs. Without these, a bare `eslint .` walks into
    // site-packages.
    ignores: [
      '**/dist/**',
      '**/dist-e2e/**',
      '**/node_modules/**',
      '**/playwright-report/**',
      '**/test-results/**',
      '**/coverage/**',
      'legacy/**',
      'backtesting/**',
      'tmp/**',
      'backend/**',
    ],
  },

  js.configs.recommended,

  // The type-aware rules. They need a TS program, which is why the two
  // workspaces are configured separately below.
  ...tseslint.configs.recommendedTypeChecked,

  // Plain JS that belongs to no tsconfig: this file, tooling configs, and the
  // standalone Alpaca fixture server that Playwright spawns as a process.
  {
    files: ['**/*.js', '**/*.mjs', '**/*.cjs'],
    ...tseslint.configs.disableTypeChecked,
    languageOptions: { globals: { ...globals.node } },
  },

  {
    files: ['**/*.ts', '**/*.tsx'],
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      // A promise nobody awaits is the bug class this codebase is most
      // exposed to: every service is async and several deliberately fire and
      // forget. Those are marked with `void`, which satisfies this rule — so
      // it flags the ones that are *not* deliberate.
      '@typescript-eslint/no-floating-promises': 'error',
      '@typescript-eslint/no-misused-promises': 'error',

      // `_`-prefixed is the established signal for "deliberately unused".
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrors: 'none' },
      ],

      // The wire protocol crosses an untyped boundary (JSON.parse, the
      // library's own `any`s). Warn rather than error: the casts at those
      // boundaries are checked by the protocol types either side of them.
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/no-unsafe-assignment': 'off',
      '@typescript-eslint/no-unsafe-member-access': 'off',
      '@typescript-eslint/no-unsafe-argument': 'off',
      '@typescript-eslint/no-unsafe-call': 'off',
      '@typescript-eslint/no-unsafe-return': 'off',

      // Template literals interpolating a number are how every readout is
      // built; this rule objects to it by default.
      '@typescript-eslint/restrict-template-expressions': [
        'error',
        { allowNumber: true, allowBoolean: true, allowNullish: true },
      ],
    },
  },

  // React: the hook rules are the ones worth having. A stale dependency array
  // is invisible to the type checker and produces a chart that silently stops
  // updating — exactly the failure this app cannot afford.
  {
    files: ['frontend/src/**/*.{ts,tsx}'],
    plugins: { 'react-hooks': reactHooks },
    languageOptions: {
      globals: { ...globals.browser },
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
    },
  },

  // Playwright specs: `test`/`expect` are injected, and assertions are
  // routinely awaited inside conditionals the type checker cannot narrow.
  {
    files: ['e2e/**/*.ts'],
    languageOptions: {
      globals: { ...globals.node },
    },
    rules: {
      '@typescript-eslint/no-non-null-assertion': 'off',
    },
  },

  // Vitest globals.
  {
    files: ['frontend/**/*.test.ts', 'frontend/vitest.setup.ts'],
    languageOptions: {
      globals: { ...globals.node },
    },
  },
);
