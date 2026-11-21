---
decider: [core]
decided_on: 2026-11-19
valid_from: 2026-11-19
state: in_force
subject: viewer-slip
---

# The slip: the first sheet of the reference viewer

A reader takes one conclusion, sees what it rests on, moves a fact, and checks the result without trusting the engine or the page.
The slip is the sheet that does this for one derived row.
It shows the sentence, the lines the row rests on, and a seal that says who checked what.
It needs no positions and no layout engine, so it does not wait for the drawing views or for the first release.
On 2026-11-21 the owner moved the browser slip page to `rezono-lang/cartouche` (`packages/slip`, consumed at a pinned version) while keeping the data side and screenless readers in `rezono-lang/rezono` (see [Repository boundary](#repository-boundary)).
[Vision](../docs/vision.md) · [EPL-2.0 and generic views](runtime-epl-and-generic-views.md) · [View contract](../contracts/view.yaml) · [Proof contract](../contracts/proof.yaml) · [Explanation contract](../contracts/explain.yaml) · [Release 1 scope](release-1-scope.md)

## Name

The sheet is named `Slip`.
`Receipt` was considered and rejected: `CompletenessReceipt` is already evidence of a complete read, and a transparency log issues receipts as well.

## What stays fixed

1. The page computes nothing. It never adds, rounds, compares, picks or interpolates. Every total it shows is a published value: an aggregate result or a calculation step.
2. The page has no answer of its own to any question. It asks the reader, and shows a verb only when the reader answers that verb's question for that line.
3. The page's code holds no reader text. Every word comes from a message catalogue: the pack's for its own sentences, `std-view` and `std-explain` for the words of the sheet, in English and in Dutch.
4. The page knows no word of any pack. Its folder and its tests are guarded by the domain-free test.

## Repository boundary

On 2026-11-21 the owner set the boundary between `rezono-lang/rezono` and `rezono-lang/cartouche` for reading:

- **What stays in `rezono-lang/rezono` (Release 1 reading is the data side):**
  - the contracts (`contracts/`) and `packs/std-view`;
  - per-role bundles, head status (`witness_check`), and manifest hash (`manifest_sha256`);
  - the key of signs in every schema bundle;
  - sweeps and turning points;
  - message formatting and canonical helpers (`viewer/messages/src/fill.ts` and `viewer/src/lib/canon.ts`);
  - screenless readers (REPL, MCP, and CLI).
- **What moves to `rezono-lang/cartouche`:**
  - the browser slip page (`packages/slip` in `rezono-lang/cartouche`, consumed at a pinned version), tested against the same conformance requirements in this decision and against Rezono's fixtures;
  - once the slip tests are green on `rezono-lang/cartouche`'s `main`, `viewer/slip/` and the DOM slip tests leave `rezono-lang/rezono`, while all data-side tests remain in `rezono-lang/rezono`.
- **CI independence:** `rezono-lang/rezono`'s CI does **not** depend on `rezono-lang/cartouche`'s CI.

## Steps

| Step | What the reader gets | What it needs |
| --- | --- | --- |
| 1 | the sentence, the lines and the seal, with the verbs why and depends | the role's part of the bundle in the local reader; code that fills a message |
| 2 | what if, on the line | several sweeps; the difference of a variant in the local reader; turning points |
| 3 | one file for one role, with the hashes checked in the page | one role's cut of the store; a reader that runs without Node |
| 4 | the verbs missing, compare and propose | the questions the local reader does not answer yet; a gate for propose |
| 5 | the witnesses checked in the page | a second checker that runs as WebAssembly |

This decision settles steps 1 and 2. Steps 3 to 5 each get their own decision when they start.
A part appears on the page when its step is there; nothing is shown that the reader cannot answer.

## The role's part of the bundle

The stored bundle is not per role, so the page never reads it.
The local reader in `edge/gate/` gives a page the role's part, at `GET /<pack>/bundle?m=<manifest>`, beside the catalogue it already gives:

- `rules`: every rule whose head relation and every relation of whose body the role reads, as the bundle has it, body included.
- `labels`: the labels of the kinds, slots and relations in the role's catalogue and of the rules it gives.
- `messages`: one resource per language, holding the message `rule.<id>` of each rule it gives, and every message whose id names no kind, slot, relation, rule or check of the pack. A message whose id names such an element is given only with that element; a check's message is not given in steps 1 and 2.
- `home`: the pack's home claim, with only the relations the role reads.
- `questions`: the questions of the bundle. A question names no element of a pack.

The catalogue part of the response carries the type and naming fields the slip needs to name elements, format amounts and semantic values, and tell calculated and outcome rows apart without guessing, scoped strictly to what the role reads:

- **Kinds (`kinds`):** `name_attribute` when that attribute is in the role's `attributes`; and `name_arrows` restricted to arrows in the role's `arrows`, in bundle order (omitted when none are visible).
- **Attributes and arrows (`attributes`, `arrows`):** `semantic` on each slot in the role's catalogue, and `currency` on an attribute when declared.
- **Relations (`relations`):** `calc` when the relation is a calculation's view (so the slip knows a row carries calculation steps rather than rule premises), `outcome` when the relation is a named outcome and its named kind is in the role's `kinds`, `semantic` on the relation when present (the calculation view's value type), and per column `currency` and `semantic` when present (omitting a column's `semantic` if its `target` names a kind the role does not read).

A role reads a relation when its snapshot of it is full or holds a row. A snapshot that is empty and not full says only that nothing of the relation is granted, so the catalogue follows the same rule: a kind, slot or relation the role does not read is not in it either, and none of its type fields, currencies or semantics appear anywhere in the response.
Something left out looks the same as something that does not exist.
This touches access: the first change that lands it is reviewed for a role that receives anything of a kind it does not read.

The reader's head (`GET /<pack>/head`) gains two fields:

- `witness_check`: the status of the check of the witnesses (`rezono:proofs`) in the manifest, and nothing else of that check. A check's name can name a kind, so the head gives the status only. A manifest without that check gives no `witness_check`.
- `manifest_sha256`: the hash of the manifest, as the head object names it. The seal shows it as the one value to compare with the publisher's.

## Filling a message

One module fills a message, and the page, the REPL and the MCP server share it.
It lives in `viewer/messages/`, a folder of its own with its own `package.json`, not under `viewer/src/lib`: the view build counts `viewer/package.json` and every file under `viewer/src/lib` as inputs of a kept view, and a change to the slip must not change those.

`viewer/messages/src/fill.ts` exports `fill(resources, lang, id, args)`.
`resources` are `MessageResource` records of the bundle, `args` maps a variable name to its text.
It returns the text of message `id` in `lang` with every `{$name}` replaced, or `undefined` when the message is not there; a caller then shows the id, as the bundle contract says for a rule without a message.
A variable that the message uses and `args` does not give is an error (`MissingMessageArgument`), never an empty text.

## The sentence

- The slip opens on the row of the first relation in the role's home claim of which the role reads exactly one row. Without one it opens on the list of relations the role reads, and the reader picks a row. That list is one key away from every slip.
- For a rule row the sentence is the message `rule.<id>` filled with the bindings of the chosen witness, each as its canonical text. A rule without a message shows its rule id.
- A calculated row has no sentence yet. The slip shows the label the bundle gives its rule, and its value.
- A variable in the sentence links to the line of the premise that binds it: the n-th `atom` literal of `Rule.body`, counted from 0, is the premise at `AnswerStep.position` n. A variable that an aggregate binds links to that aggregate's total. Any other variable is plain text.
- A row with several witnesses shows the chosen proof, as `grounds` does.

## The lines

A line is one row: its label, its value with its state, its sign from the key, and its origin (a fact's source, a conclusion's rule).

| Ground in the witness | Line on the slip |
| --- | --- |
| a positive premise | the row and its value |
| a negative premise | the row, checked absent |
| an aggregate | its result as a total, with its contributing rows as lines under it |
| a calculation | the steps of the `CalcWitness`, nested by `path`; a node's value is the total of its arguments |

- For a rule row the lines are the nodes at distance 1 of the `grounds` answer, in the answer's order, none added and none dropped.
- For a calculated row the lines are the steps of its `CalcWitness`, in their order. A constant has no step and so no line.
- A completeness row is a positive premise like any other.
- A line that is itself a conclusion opens to its own slip, in place.
- Where an answer stopped at its limit, the slip shows the continuation the answer names.
- A value whose state is not `known` shows the sign of its state and the message of its reason, and no digit. A total above it shows the state the publication gives that total.

## The seal

The seal lists each check on its own line, with who ran it. It never says "checked here" for a check that ran somewhere else.

| Check | Step | What the seal says |
| --- | --- | --- |
| the reader's hashes | 1 | the local reader hashed every object it read for this slip against the id the manifest names |
| the publisher's record | 1 | the head's `witness_check`, quoted as the publisher's claim |
| hashes in the page | 3 | the page hashed every embedded object itself |
| witnesses in the page | 5 | every witness on this slip was checked in the page |

- The local reader answers no request that needs an object whose hash fails. The page then shows no line and says that the reader could not serve the publication.
- The seal shows `manifest_sha256`. Without a comparison with the publisher's value it says consistent, not authentic.

## The verbs

The verbs stand on every line in the order, with the keys and the labels that `Sheets.verbs` in `packs/std-view/sheets.yaml` gives.
The viewer build takes `std-view` in; no pack publishes it.

- For a verb with a `question`, the page asks that term. For a verb without one, it selects among the questions the reader gives by `start` and `answer`, as the gate does.
- The page shows a verb on a line when the reader answers its question for that line, and for no other reason. A reader that answers one more question makes one more verb appear, without a change to the page.
- Step 1 has why (`grounds`) and depends (`reach`). Step 2 adds suppose on a line whose cell a sweep moves, and compare for a variant of a sweep.

## Tables, legend, keys and language

- The slip is a table, and so is every answer a verb opens: a route as indented rows, rings as rows grouped by distance, a series as one row per stop. Every table has headers.
- The legend lists every sign the page draws, from the key of `std-view`. A sign that is not in the key is not drawn.
- Every action has a key; the verb keys come from `std-view`. Focus stays on the line when the page draws again.
- Svelte 5, built to static files. This sheet uses no layout library and no chart library.

## The page and how it gets its answers

- During the transition the page lives in `viewer/slip/`, with its own `package.json`, outside `viewer/src/lib`. Under the [repository boundary](#repository-boundary), the browser slip page moves to `packages/slip` in `rezono-lang/cartouche` (consumed at a pinned version), and `viewer/slip/` leaves `rezono-lang/rezono` once the slip tests are green on Cartouche's `main`.
- In step 1 a local command, `node viewer/slip/bin/serve.ts --store <directory> --role <role>`, opens the local reader for the role its caller chooses, as the REPL does. It serves the page and the reader's routes on the loopback address only, while the command runs, and refuses a request whose `Host` is another name. This is local use: no gate and no hosting.
- In a test the page gets the reader's handler directly, without a server. `viewer/slip/bin/render.ts` reads one JSON request on standard input and writes one JSON result on standard output:
  - request: `store` (a directory the publisher wrote), `role`, `pack`, `lang`, optionally `row` (`relation` and `key`, else the slip opens as above), optionally `keys` (actions on the line with the given index, in order: a key press as `{"line": n, "key": "w"}`, or the control of a sweep moved to a stop as `{"line": n, "stop": i}`, which the arrow keys do one stop at a time), and optionally `reader` (the path of a module whose default export takes the reader's handler and returns another; a test uses it to add or remove a question);
  - result: `html`, the page's document body after the keys, drawn in a simulated DOM; and `files`, the sha256 of each file of the built page, by path.
  The page installs its own dependencies from its lockfile; the tests run `npm ci` in `viewer/slip/` once before they render.
- The same question gives the same rows in the page, in the REPL and through MCP. The same publication and the same build give the same bytes.

### Generated contract types

`viewer/messages/` (and `viewer/slip/` while it remains in `rezono-lang/rezono` during the transition) import their generated TypeScript contract types (`import type`) directly from `contracts/typescript/generated/`, the directory `contracts/gen-types.sh` already writes for `edge/gate/` and `tools/repl/`.
Neither package writes into or reads generated types from `viewer/src/lib/contract/generated/`, and `contracts/gen-types.sh` does not write into `viewer/src/lib/` for them: every file under `viewer/src/lib/` is an input of a kept view's build hash (`edge/publisher/rezono_publisher/view_build.py`), so generated output for the slip and message filler stays outside `viewer/src/lib/`.

### Marks in the drawn page

The text on the page comes from messages, so tests find the parts by attributes, which carry no reader text:

| Part | Mark |
| --- | --- |
| the slip | `table[data-sheet="slip"]` |
| the sentence | `[data-part="sentence"]`; a variable in it is `a[data-line]` with the index of the line it links to |
| a line | `tr[data-line]`, whose value is its index from 0 in the slip, with `data-relation`, `data-key` (the canonical key as JSON), `data-depth` (0 for a line of the row, one more under a total or a calculation node), `data-polarity` (`positive` or `negative`), and for a calculation step `data-path` |
| a total | `tr[data-line][data-part="total"]` |
| a value | `td[data-part="value"]` with `data-state`, and `data-reason` with the published reason where the state is not `known`; its sign is an element with `data-sign`; in a fold the old value is in `del` and the new one in `ins` |
| a verb | `button[data-verb]` with `data-key`, inside the line it acts on |
| an answer a verb opened | `table[data-answer="<question term>"]` with a header row |
| the seal | `[data-part="seal"]`, with one `[data-check]` per check (`reader-hashes`, `publisher-record`) and `[data-part="manifest-hash"]` |
| the legend | `table[data-part="legend"]`, one `tr[data-sign]` per sign |
| a reader that could not serve | `[data-part="unserved"]` |
| a stop of a sweep | `[data-stop]` inside the line of the swept cell, with the grid index, `data-status`, and `data-turn` (`turns`, `same` or `unknown`); a red stop holds one `[data-check]` per check, with its `data-status` |

## Every example with a home claim

Each example pack with a home claim records by hand, in `slip.yaml` beside its `channels.yaml`, what the slip shows first: `role`, `lang` and `sentence`.
The test over the examples reads that file, names no pack, and renders each with the same build of the page.
`examples/platform` gets a second claim whose row comes from a rule with a count, over a relation the shown role reads in full, so that at least two packs with a claim exist and one sentence rests on an aggregate.

## Several sweeps

A pack may declare up to four sweeps.
The number stays in the compiler (`MAX_SWEEPS` in `compiler/rezono_compiler/pack.py`), and `contracts/pack.yaml`, `contracts/explain.yaml`, `edge/gate/src/sweep.ts` and `tools/repl/src/session.ts` follow it.
Reason: each grid value costs one evaluation of the pack, so the cost of a sweep run grows with the number of sweeps, and four sweeps of at most 64 values bound it at 256 evaluations per main. A reader of a scheme usually wants to move more than one fact, such as an income and a cost, so one sweep is too few; no bound at all would let one pack make a publication run unbounded.
A variant's id already names its sweep (`v-<sweep>-<index>-<epoch>`), so variants of two sweeps never collide.
The local reader lists every sweep whose cell the role reads, and `sweep` answers each by name, in the REPL too.

## What if, on the line

- A fact line whose cell a sweep moves carries a control with one stop per grid value and nothing in between.
- A sweep moves one fact cell that the pack marks with `explore`. A row that carries a decision keeps it in a variant, and the slip shows its value with the sign `supposed`.
- A stop shows its status: `green`, `warning`, `red`, `not_computed` or `unavailable`. A red stop shows its checks and no value. For a role that does not read every relation in full every stop is `unavailable`, and the control says so.
- Moving the control selects the variant of that stop. The slip then shows the fold from the difference of that variant: the old value struck, the new value beside it.
- The local reader serves that difference through `scenario` for a variant of a sweep, for a role that reads every relation in full, with each changed row and what it was. The other questions in `blocked/edge-gate-variant-queries.txt` stay outside this decision.

## Turning points

A turning point is a stop where a row's outcome changes in kind, not only in size.

### When a row is the same row

At two stops, a row is the same row when:

- for a row of a calculation rule's view: it has the same rule and the same subject;
- for any other row: it has the same relation and the same key prefix, all columns but the last, and it is the only row with that prefix on each side. This is the rule by which a difference already reports `changed` (`DifferenceChange` in `contracts/explain.yaml`), so the fold and the turning points pair rows the same way.

Rows that cannot be paired so are a row on one side only, on each side.

### When two stops differ in kind

Between two stops a row turns when, anywhere in its proof back to the facts, rows paired as above differ in one of these ways:

| Cause | Difference |
| --- | --- |
| `rule` | another `rule_id` of the witness, or another calculation rule |
| `version` | another `version` of a calculation |
| `definition` | another `definition` of a calculation |
| `path` | another set of step paths: another branch of an `if`, another argument evaluated |
| `count` | another `count` of an aggregate |
| `contributors` | other keys among the contributors of an aggregate |
| `state` | another value state |
| `presence` | the row, or a row of its proof, on one side only |
| `value` | another value where the value is a reference, an enum value or a boolean |
| `cap` | a `min` or `max` step took another argument (see Caps) |

An amount, a quantity, a number or a date that differs along the same proof is no turning point.

### Caps

A cap is a turning point.
A reader who sees an amount stop growing asks where the cap took over, and without a mark the page could only show the numbers, which it may not compare.

The argument a `min` or `max` step took is the one whose value equals the step's value, the lowest index on a tie.
Every argument's value is already published: an evaluated argument has its own step, at the step's path plus its index, and a constant stands in the program (`ir/calc.json`), which the publisher and the checker both read.
So the publisher derives the taken argument when it writes turning points, and the checker derives it again when it checks them; the witness contract does not change.
Two alternatives were considered.
Adding the taken argument to `CalcStep` would change the bytes of every published witness with a `min` or `max`, for a value that follows from what is there.
Leaving caps out would keep the work smaller, but the most common turn in a scheme with a ceiling would then go unmarked.
A step whose value is not known took no argument, and its state decides instead.

### Publishing and serving

- A variant depends on its base and its value alone, so turning points go in an object of their own, written when both stops are there: `rezono.turns/1`, one per role, per sweep and per pair of neighbouring stops that both have a variant. It names the two stops by index and manifest, and lists each conclusion the role reads that turns between them, with its causes, in key order. Only a conclusion turns: a row with a witness or a calculation witness at one of the two stops. A fact that moves is the cause of a turn, never a turning point itself.
- A turning point is marked only between two stops that both have a variant. Where a neighbour has none, the stop says that it is not known whether the outcome turns there.
- A role sees a turning point only where it sees the status of both stops.
- The checker recomputes every turns object from the two variants' witnesses and blocks one that lists a row too many or too few.
- The proof on both sides is the row's proof in the two variants.
- `sweep` takes an optional start row, as `relation=` and `key=` beside `sweep=`. With one, the answer's `start` is that row, and each `SeriesCell` also carries `row`, the row at that stop paired as above (absent where the row is not there), and `turn` against the stop before: `turns` with its `causes`, `same`, or `unknown`; the first stop has no `turn`. A new question was the alternative; it would repeat the whole series, need a start that is both a row and a sweep, and add a term to `std-explain`, while the series, its statuses and its access are already those of `sweep`.

## Out of scope

Positions and the drawing views. Hosting, and a gate with sign-in. Signing a statement. An assumption that is not on a grid. Embedding the slip in another page or in a conversation with an agent; that reuses the file of step 3.

## Tests

Each test below is a red test first, with its expectation written by hand in a fixture or computed by an oracle in the test.
The tests of the page use `tests/fixtures/slip`, a small pack with two roles, and name no example pack.
Under the [repository boundary](#repository-boundary), `tests/fixtures/slip` and the data-side tests (`verb-bar-in-std-view`, `role-part-of-bundle`, `role-bundle-type-fields`, `head-status-and-hash`, `message-filled`, `several-sweeps`, `variant-difference-local`, `turning-points`, `turn-unknown-neighbour`) remain in `rezono-lang/rezono`.
The DOM slip tests (`slip-rule-row`, `slip-calculated-row`, `unknown-shows-no-digit`, `verbs-that-answer`, `tables-and-legend`, `unserved-publication`, `one-build-every-claim`, `no-pack-word`, `stops-only`) are conformance tests for `packages/slip` in `rezono-lang/cartouche` against Rezono's fixtures; they remain in `rezono-lang/rezono` until the slip tests are green on Cartouche's `main`, after which `viewer/slip/` and the DOM slip tests leave `rezono-lang/rezono`.

Step 1: `verb-bar-in-std-view`, `role-part-of-bundle`, `role-bundle-type-fields`, `head-status-and-hash`, `message-filled`, `slip-rule-row`, `slip-calculated-row`, `unknown-shows-no-digit`, `verbs-that-answer`, `tables-and-legend`, `unserved-publication`, `one-build-every-claim`, `no-pack-word`.

Step 2: `several-sweeps`, `variant-difference-local`, `turning-points`, `turn-unknown-neighbour`, `stops-only`.

Step 3, named here and written when it starts: `role-cut`, `reader-without-node`, `tampered-object-named`, `no-request`.
