---
decider: [language]
decided_on: 2026-11-20
valid_from: 2026-11-20
state: in_force
subject: language-guide-highlight
---

# Language guide excerpt, syntax highlighting and SVG preview

The language guide ([`rezono/README.md`](../rezono/README.md)) opens with the language itself rather than its table of source files: a copyable Rezono excerpt taken byte-for-byte from `examples/subsidy-scheme/rezono/award.rezono`, links to where the syntax is described ([`docs/rezono/v0.md`](../docs/rezono/v0.md) and [`docs/rezono/expressions.md`](../docs/rezono/expressions.md)), and a syntax-highlighted SVG rendering in light and dark themes showing Rezono's own token colors before the source-file table.

The repository's root [`README.md`](../README.md) receives no SVG image; it shows the excerpt as copyable fenced code only.

## Fence label for copyable code blocks

GitHub highlights fenced code blocks only for languages registered in Linguist, so a `rezono` fence renders monochrome. Both the root readme and the opening code block of [`rezono/README.md`](../rezono/README.md) use the `haskell` fence label: GitHub colors `--` comments, capitalized type names, numbers, symbolic operators, `then`, and `else`, and does not misread `#` inside `@` source citations as comments (unlike `python` or `ruby`). Rezono's own keywords (`derived`, `version`, `valid`, `known`, `definition`, `output`, `unit`) stay uncolored under `haskell`, which is why the language guide also shows the language's own colors below the copyable block.

## Choice: highlight directly from the reader's grammar, with zero new dependencies

We generate the two SVG previews directly from the reader's own grammar and generated TextMate grammar (`rezono/src/grammar.ts`, `rezono/src/rule-names.ts`, and `rezono/src/syntax-grammar.ts`), with **no new npm dependencies**.

A deterministic TypeScript command, `rezono/src/render-excerpt-svg.ts` (exposed as `"excerpt-svg": "node src/render-excerpt-svg.ts"` in [`rezono/package.json`](../rezono/package.json)), reads:

1. the opening fenced code block of [`rezono/README.md`](../rezono/README.md);
2. the token definitions produced from Rezono's own grammar (`rezono/src/syntax-grammar.ts` / `rezono/src/grammar.ts` and `rezono/src/rule-names.ts`);
3. the light and dark color palettes from the data file `rezono/highlight-theme.json`.

It renders two self-contained, deterministic SVG files (no timestamps, no external font requests, fixed line grid, XML-escaped `<text>` lines with `<tspan>` spans whose concatenated text per line equals the excerpt verbatim):

- Light theme SVG: `rezono/assets/excerpt-light.svg`
- Dark theme SVG: `rezono/assets/excerpt-dark.svg`

Running `node rezono/src/render-excerpt-svg.ts --out-dir <dir>` writes `<dir>/excerpt-light.svg` and `<dir>/excerpt-dark.svg` without modifying tracked files, so tests can verify deterministic regeneration directly. Both committed SVGs are checked into git because people read them directly in `rezono/README.md` (`AGENTS.md`, "No generated output in git, except where a person reads it").

## Token kinds and color data file

Every token emitted by the highlighter belongs to one of eleven token kinds:

| Token kind | What it covers |
|---|---|
| `comment` | `--` line comments |
| `function` | aggregate and function call names (`round`, `min`, `max`, `sum`, `count`, `any`, `all`, `none`) |
| `identifier` | plain names (`cost_share`, `assessed_income`, `cents`) |
| `keyword` | reserved and contextual keywords (`derived`, `version`, `valid`, `known`, `definition`, `when`, `then`, `else`, `and`, `or`, `not`, `output`, `unit`, `param`, `extend`, ...) |
| `number` | integers, decimals, dates, datetimes, percentages, and quantities |
| `operator` | symbolic operators (`<=`, `<`, `>=`, `>`, `=`, `!=`, `..<`, `..`, `+`, `-`, `*`, `/`, `=>`, `->`) |
| `punctuation` | structural punctuation (`:`, `,`, `.`, `(`, `)`, `[`, `]`, `{`, `}`, `|`) |
| `source` | `@source#locator` citations |
| `state` | truth and four-state literals (`true`, `false`, `n/a`, `unknown`, `invalid`) |
| `string` | double-quoted text literals and backtick-quoted identifiers |
| `type` | capitalized kind and type names (`Int`, `Application`, `SchemeParameter`) |

All colors live in `rezono/highlight-theme.json` — never hardcoded in TypeScript or Python code (`AGENTS.md` rule 1):

```json
{
  "themes": {
    "light": {
      "background": "#...",
      "border": "#...",
      "foreground": "#...",
      "tokens": {
        "comment": "#...",
        "function": "#...",
        "identifier": "#...",
        "keyword": "#...",
        "number": "#...",
        "operator": "#...",
        "punctuation": "#...",
        "source": "#...",
        "state": "#...",
        "string": "#...",
        "type": "#..."
      }
    },
    "dark": {
      "background": "#...",
      "border": "#...",
      "foreground": "#...",
      "tokens": {
        "...": "#..."
      }
    }
  }
}
```

Every token kind listed above has a six-digit hex color (`#RRGGBB`) in both `light` and `dark`, and the light and dark themes use distinct palettes suitable for GitHub's light and dark color schemes.

## Display in `rezono/README.md`

Immediately underneath the opening `haskell` code block (and before the source-file table), [`rezono/README.md`](../rezono/README.md) displays the highlighted preview with `<picture>` so GitHub selects the matching theme automatically:

```html
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/excerpt-dark.svg">
  <img alt="Syntax-highlighted Rezono excerpt of the subsidy award calculation rules" src="assets/excerpt-light.svg">
</picture>
```

Directly underneath `</picture>`, one single line states which color represents which token kind (naming the colors and token kinds shown in the excerpt).

## Considered

- **An existing TextMate execution package (`shiki`, or `vscode-textmate` with `vscode-oniguruma`).** Adds a WASM Oniguruma runtime and/or bundled grammar sets to `rezono/package.json` and `rezono/package-lock.json`, which every Python CI job installs via `npm ci`. Because `rezono/src/syntax-grammar.ts` already generates JavaScript-compatible regular expressions directly from Rezono's Ohm grammar, pulling in a full Oniguruma stack is unnecessary bloat and extra lockfile/licence maintenance.
- **Standalone hand-written highlighter code independent of the grammar.** Duplicates Rezono's keyword lists and lexical rules in a second place, risking silent drift whenever the language grammar changes.
- **Putting the SVG preview in the root `README.md`.** An image cannot be copied and pasted by a newcomer reading the front door; the root readme keeps copyable fenced code only, and the language guide shows Rezono's own colors beside the copyable block.

## Tests that follow

- `rezono/test/test_language_guide_excerpt.py`: checks that [`rezono/README.md`](../rezono/README.md) opens before its source-file table with a `haskell`-fenced excerpt copied byte-for-byte from `examples/subsidy-scheme/rezono/award.rezono` and links to where the syntax is described.
- `rezono/test/test_language_guide_highlight.py`: four tests (waiting on `rezono/test/test_rezono_syntax_grammar.py--test_generated_syntax_highlighting_grammar`, and for the excerpt-dependent checks also on the language guide excerpt test):
  1. regenerating the light and dark SVGs produces identical bytes matching the committed files;
  2. the text content inside both SVGs equals the excerpt verbatim;
  3. every declared token kind has a valid hex color in both light and dark themes in `rezono/highlight-theme.json`, with no hex colors hardcoded in `rezono/src/render-excerpt-svg.ts`;
  4. [`rezono/README.md`](../rezono/README.md) displays the `<picture>` with descriptive `alt` text, both SVG files, and the one-line color legend underneath the opening code block.
