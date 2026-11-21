---
decider: [core, language]
decided_on: 2026-11-21
valid_from: 2026-11-21
state: in_force
supersedes: [conformance-value-viewer-invalid-arrow]
subject: viewer-invalid-sign
---

# Use `!` as the `invalid` status sign in `std-view` and the slip model

A value in state `invalid` (for example division by zero or `multiple_values` from a functional derivation) is neither a rule breach (`violated`, `✕`) nor incomplete knowledge (`unknown`, `▨`). This decision settles the status sign, palette contrast requirements, and slip-model mapping for `invalid`, closing [`docs/semantics/value-cases.yaml#viewer-invalid-arrow`](../docs/semantics/value-cases.yaml) and superseding [`decisions/conformance-value-viewer-invalid-arrow.md`](conformance-value-viewer-invalid-arrow.md).

## Decision

1. **Dedicated `invalid` status in `contracts/view.yaml` and `packs/std-view`:**
   - `StatusName` in [`contracts/view.yaml`](../contracts/view.yaml) includes `invalid` alongside `violated` and `unknown`.
   - [`packs/std-view/key.yaml`](../packs/std-view/key.yaml) assigns `invalid` the unique non-colour glyph **`!`**, `tone: negative`, `color_role: status.invalid`, and `label_message: status.invalid` (with English and Dutch entries in `packs/std-view/messages/{en,nl}.mf2`).
   - Every status in `packs/std-view/key.yaml` keeps a distinct glyph (`!` for `invalid`, `✕` for `violated`, `▨` for `unknown`) so the distinction holds without colour.

2. **Palette contrast against both `paper` and `ink`:**
   - [`packs/std-view/palette.yaml`](../packs/std-view/palette.yaml) defines `status.invalid` across `light`, `dark`, `print`, and `forced_colors` (`CanvasText` in `forced_colors`, where the `!` glyph and label convey status).
   - In `light`, `dark`, and `print`, `status.invalid` must satisfy BOTH:
     - **>= 4.5:1** contrast against `paper` (WCAG 1.4.3 AA text legibility), AND
     - **>= 3.0:1** contrast against `ink` (WCAG 1.4.1 / G183 distinguishability from surrounding body text).
   - Both bounds are simultaneously achievable in all three themes (for `light` paper `#faf8f3` / ink `#1c1b19`, `dark` paper `#17181b` / ink `#ebe8e1`, and `print` paper `#ffffff` / ink `#000000`).

3. **Slip model (`viewer/slip/src/model.ts`):**
   - `stateSign` in `viewer/slip/src/model.ts` maps `ValueState` `'invalid'` to the `std-view` `'invalid'` sign (`!`), never to `'violated'` (`✕`).
   - Any viewer rendering a reference or value in state `invalid` beside `unknown` displays `!` (`status.invalid`) for `invalid` and `▨` (`status.unknown`) for `unknown`.

## Tests

- [`contracts/python/tests/test_std_view_statuses.py`](../contracts/python/tests/test_std_view_statuses.py): verifies `StatusName`, unique glyphs (`!` vs `✕`), en/nl labels, >= 4.5:1 contrast on `paper`, and >= 3.0:1 contrast against `ink` for `status.invalid`.
- [`tests/slip/test_invalid_sign.py`](../tests/slip/test_invalid_sign.py): verifies that `viewer/slip/src/model.ts` (`buildRuleSlipView`) maps `invalid` to the `invalid` sign (`!`) rather than `violated` (`✕`), while keeping `unknown` on `▨`.

## Considered

- **Reusing `violated` (`✕`) for `invalid` values.** Rejected: conflates an expression or data-multiplicity error (`invalid`, e.g. `multiple_values` or division by zero) with a rule or constraint breach (`violated`).
- **Rendering an invalid reference as `unknown` (`▨`).** Rejected: hides a contradiction or error behind incomplete knowledge, contrary to Rezono's explicit four-state model.
- **Requiring >= 4.5:1 against both `paper` and `ink` simultaneously.** Rejected: mathematically impossible for the `light` (max 4.04:1) and `dark` (max 3.84:1) `paper`/`ink` pairs; >= 4.5:1 on `paper` paired with >= 3.0:1 against `ink` matches WCAG 1.4.3 and WCAG 1.4.1 (G183) and is feasible in every display theme.
