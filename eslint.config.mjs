// JS coding standard. Run without installing anything:
//   npx --yes prettier@3.9.10 --write <files>
//   npx --yes eslint@10.14.0 05_twin_2d 04_synthetic_data
// shortcut: core "recommended" rules listed by hand so no @eslint/js install is needed;
// switch to js.configs.recommended if a package.json is ever added.
const rules = {
  "no-undef": "error",
  "no-unused-vars": ["error", { args: "none", caughtErrors: "none" }],
  "no-redeclare": "error",
  "no-dupe-keys": "error",
  "no-dupe-args": "error",
  "no-duplicate-case": "error",
  "no-const-assign": "error",
  "no-unreachable": "error",
  "no-self-assign": "error",
  "no-cond-assign": "error",
  "no-empty": ["error", { allowEmptyCatch: true }],
  "no-fallthrough": "error",
  "use-isnan": "error",
  "valid-typeof": "error",
  "no-unsafe-negation": "error",
  "no-sparse-arrays": "error",
  "no-func-assign": "error",
  "no-import-assign": "error",
  "no-shadow-restricted-names": "error",
  "no-useless-escape": "error",
  "prefer-const": "off",
};

const g = (names) => Object.fromEntries(names.map((n) => [n, "readonly"]));
const shared = [
  "console",
  "setTimeout",
  "clearTimeout",
  "setInterval",
  "clearInterval",
  "URL",
  "TextDecoder",
  "DecompressionStream",
  "Blob",
  "fetch",
  "performance",
];
const browser = g([
  ...shared,
  "window",
  "document",
  "self",
  "caches",
  "localStorage",
  "requestAnimationFrame",
  "getComputedStyle",
  "alert",
]);
const node = g([
  ...shared,
  "process",
  "__dirname",
  "Buffer",
  "require",
  "module",
]);

export default [
  {
    ignores: [
      "02_data/**",
      "06_deliverables/**",
      "graphify-out/**",
      ".ua/**",
      "**/data/*.js",
    ],
  },
  {
    files: ["05_twin_2d/app.js", "05_twin_2d/sw.js"],
    languageOptions: { sourceType: "script", globals: browser },
    rules,
  },
  {
    files: ["04_synthetic_data/**/*.js", "05_twin_2d/tools/*.js"],
    languageOptions: { sourceType: "commonjs", globals: node },
    rules,
  },
];
