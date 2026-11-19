# The first packs in the language

The language reads and lowers most building blocks of a pack. This decision says which packs go first, how a conversion is done and checked, and how far this stage goes. "Where it stands" below says what the repository holds now.

## Which packs first

- `run/packs/exact-quote`: the usage table already names every building block it uses supported.
- `packs/std-access`: the smallest standard pack. Only schema metadata holds it back.

Standard packs go before other packs, because other packs import them. The owner of a pack converts it.

## Where it stands

- **The converter exists.** `scripts/convert_pack.py` writes a candidate into a separate directory and compares it with the pack it came from. It also accepts a pack whose rules form a module of their own, and enum members written without a body.
- **`run/packs/exact-quote` is converted.** Its schema and rules are `rezono/quote.rezono` with its form, declared in its `pack.yaml`. `run/fixtures/exact-quote-linkml/` keeps the replaced files as the oracle, and `run/tests/test_exact_quote_language.py` compares both forms on every pull request. [Exact-quote pack written in Rezono](run-exact-quote-language.md) records the two edits without meaning that came first.
- **`packs/std-access` is in progress.** The oracle fixture is in `compiler/tests/rezono/fixtures/std-access-legacy`, and `test_whole_std_access_has_the_same_meaning` in `compiler/tests/rezono/test_whole_std_access.py` is the red test for the conversion itself.
- **`examples/library` has a candidate in progress.** [Acceptance of the library migration](language-library-acceptance.md) says where the candidate is staged and how it is checked; `compiler/tests/rezono/test_whole_library.py` holds the whole-pack test, still red.

## How a pack is converted

1. `scripts/convert_pack.py` writes a candidate into a separate directory, never into the pack: its `schema/**/*.yaml` and `rules/*.dl`, the rules as blocks with `|`. Facts and `calc/` stay as they are.
2. An author reviews the candidate and writes it to `rezono/` of the pack, declared in its `pack.yaml`.
3. The same change removes the schema and rule files that the module replaces. A module and the files it replaces cannot stay side by side in one pack: the compiler refuses a module that `pack.yaml` does not declare, and two declarations of one kind clash.
4. The change lands only when the test over the whole pack is green.

When the converter refuses a pack, the refusal becomes a red test for the language, not a hand-written workaround in the pack.

## The oracle

The existing schema and rule files are the oracle. Because the conversion removes them from the pack, they are kept as a test fixture before the conversion. A test checks that the fixture equals the files of the pack for as long as the pack still has them.

The test over the whole pack publishes the pack twice, once over the fixture and once over the pack as the repository holds it, and compares what [Comparing two source forms of a pack](language-semantic-publication.md) asks: the published files, the bundle with each place reduced to its file, and the relations each role sees. A pack that publishes nothing on its own is published through a consumer that imports it. For `std-access` that consumer is `examples/subsidy`, whose roles read the scheme, the cases or both.

After the test has been green once, a recorded print of that meaning may replace the fixture, as for every other converted example.

## Import pins

A conversion changes the files of a pack, and so its hash. The same change updates the `sha256` of the pack in every `pack.yaml` that imports it, and onwards for the packs that import those. That one line may be changed in a folder owned by someone else.

## After the conversion

New content in a converted pack is written only in the language.

## How far this stage goes

`scripts/language_usage.py` prints per pack whether the first conversion can start ("Ready"). This stage ends when at least 15 packs of `examples/`, `packs/` and `run/packs/` are Ready or converted, and `exact-quote` and `std-access` are converted. `exact-quote` is; `std-access` is not yet. Schema metadata and open worlds are the two building blocks that hold most packs back.

## Tests that follow

- `compiler/tests/rezono/test_whole_std_access.py`: the oracle fixture, the publication through `examples/subsidy`, and the whole-pack comparison.
- `compiler/tests/rezono/test_first_packs_ready.py`: at least 15 packs Ready.
- `run/tests/test_exact_quote_language.py`: the whole-pack test of `exact-quote`, owned by the owner of `run/packs/`.

## Considered

- **Converting every pack at once.** That removes the independent oracle of every pack in one step, and one unsupported construct would hold back all of them.
- **Keeping both forms in the pack until a later clean-up.** The compiler refuses it, and two hand-written forms of one pack drift apart.
- **Comparing the hash of the whole publication.** Places and definition hashes change with the source on purpose; a single digest would mix those with changes in meaning.
- **Reading the oracle from the Git history.** A test would then depend on the history of the checkout, which a shallow clone does not have.
