# A register of the checker's refusals

The checker refuses in four forms today: a finding with a `reason` code, `find(...)`, the first argument of `Unverified(...)` and `Refused(...)`, and close to two hundred English sentences (`problems.append(...)` and `raise ValueError(...)`). No code is registered anywhere, and no sentence exists in another language. A reader cannot get the explanation in their own language, and a sentence can show a value the reader may not read.

## The register

Every refusal is a code with named arguments.

- **The codes** are the enum `RefusalCode` of `contracts/checker-refusal.yaml`. Each value has a description and two annotations: `arguments`, the names of its arguments separated by spaces (empty when it has none), and `scope`, who reads it: `role` for a check over one role's snapshots and proof, `epoch` for a check over the complete epoch.
- **The sentences** are in `checker/rezono_checker/messages/en.json` and `nl.json`: one sentence per code, with each argument as a placeholder `{name}`. Every code has a sentence in both, a sentence uses only its code's arguments, and neither file has a code the register does not.
- **In the code**, `rezono_checker.refusals.Refusal(code, **arguments)` is a `str` whose text is the English sentence with the arguments filled in, and which carries `code` and `arguments`. A reader of today's strings sees the same text: the English sentence of a refusal that is a sentence today is that sentence, with its values as placeholders. `raise ValueError(...)` becomes `raise RefusalError(Refusal(...))`, and `RefusalError` is a `ValueError`, so a caller that catches one keeps working. A finding keeps `"reason": code`; its other fields are the arguments, and a free `detail` becomes named arguments.

The checker keeps its own list and shares no code with the compiler: it does not import `rezono_compiler.diagnostics`, and the compiler does not import the register.

## What an argument may carry

An argument is one of these, and nothing else:

| Kind | Names |
|---|---|
| A name from the definition | `relation`, `rule`, `kind`, `role`, `column`, `variable`, `field`, `fields` |
| A number or a position | `witness`, `premise`, `position`, `index`, `count`, `limit`, `size`, `level`, `bound` |
| A file of the publication | `file`, `path`, `tree` |
| Content of a snapshot | `key`, `value`, `bindings` |

There is no free text: no `detail`, no `message`, no sentence inside an argument. Content of a snapshot is only for the reader of the snapshots the check read. A refusal with scope `role` comes from that role's own snapshots and proof, so it shows only what the role reads. A refusal with scope `epoch` comes from the complete epoch and is shown to whoever publishes, never to a role. A sentence therefore never shows content its reader does not read.

## Order

1. The register and both catalogues, with every code the checker writes literally today in the three code forms.
2. `proof.py`: its 33 sentences and its `ValueError` become refusals.
3. `views.py`: its 60 sentences.
4. The other files, largest first: `rules.py`, `snapshots.py`, then the rest.

Every pull request that changes checker code is read before it lands. A change of a sentence in a catalogue is one too, because the catalogues are in the checker's package: what a refusal says is part of what the checker decides to show.

## Alternatives

- **Sentences only in the contract.** One file less, but the contract would hold Dutch text and a schema would carry prose for one language. Rejected.
- **Catalogues outside the checker's package.** A sentence could change without being read first, and an installed checker could not render its own refusals. Rejected.
- **Share the compiler's diagnostic list.** The checker must not depend on the compiler it checks. Rejected.
