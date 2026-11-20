# Rezono MCP over a publication

Use Node 24. Run `npm ci` in this directory for the locked MCP dependencies and `npm ci --prefix ../../rezono` for the shared language runtime. The server and the REPL use the same Rezono gate and question session.

```text
node src/main.ts --store file:///path/to/publications --role reader
```

The stdio process reads the publisher's on-disk store. The operator launching it chooses the role and already has access to that store. The role applies to every tool call. The server uses the same gate-backed role publication, named questions, language `ask`, completion and pagination as the REPL.

| Tool | Shared operation |
| --- | --- |
| `ask` | Evaluate an `ask … where …` expression and show value states and undecided reasons. |
| `grounds`, `reach`, `gap` | Ask the named question about the supplied row (`gap` accepts `null` or `"_"` for wildcard key parts). |
| `suppose` | Evaluate a `proposal` or `variant` with `:suppose` (`scenario`, or `impact` when `impact: true`). |
| `kinds`, `schema` | Ask about kinds or a named kind's fields in the role's typed catalogue, as `:kinds` and `:schema` do in the REPL. |
| `row` | Read the typed cells and outcomes for a kind and a single `id` or ordered `key` parts, as `:row` does. |
| `search` | Complete an identifier prefix the role can read. |
| `sweep` | Read the role's published sweep with `:sweep`. The gate requires the pinned base to be current. |
| `more` | Continue the previous page, or pass a row's `cursor` to continue that cell source under its original pin. |

Every tool result returns both the human-readable `text` content and a machine-readable `structuredContent` JSON object (`tool`, `ok`, `role`, pinned `pack`/`manifest`, `lines`, and the typed `rezono.answer/1` `answer`, `matches`, proposal `delta`/`response`, or `error`).

The `--gate` option selects an explicitly configured external gate. In an unlocked session, `propose` requires a `REZONO_GATE_TOKEN` and an affirmative `propose` right for the selected role from the authenticated gate's `/whoami` response. The client checks the right again before sending a proposed delta. The gate controls authorization and handling.

## Replay

Write a JSON plan with `pack` and `calls`. Each call contains a read tool's `tool` name and its `args`. Record and replay with the same local publication and role.

```text
node src/replay.ts record calls.json recording.json --store file:///path/to/publications --role reader
node src/replay.ts replay recording.json --store file:///path/to/publications
```

The recording stores the exact manifest, role, tool arguments, text and refusal status. Replay verifies access to that retained manifest before running any call and compares the responses byte for byte.

## Dependencies

The lockfile pins the MCP SDK 1.32.2 and Zod 4.6.7 directly, and Jose 6.2.17 through the SDK. Their licenses are MIT. The remaining locked licenses are MIT, ISC and BSD.
