# A planner may re-pin the imports of a fixture pack

The owner approved this exception on 19-11-2026.

A pack that imports another one pins it: its `pack.yaml` names the imported pack's `sha256`, the hash of that pack's definition files (`pack_hash` in `compiler/rezono_compiler/modules.py`).
A change to the imported pack gives it a new hash, so every pack that imports it must take the new pin in the same pull request.
Some of those packs are fixtures: their `pack.yaml` sits under a test or fixture directory, so `scripts/red_guard.py` protects it.
When the change to the imported pack is what turns a red test green, as when `packs/std-access` moves to the Rezono language, the same pull request also lifts that test's mark.
The guard refuses a lifted mark beside any other protected change ("Lift marks in a pull request of their own"), so that pull request could not land.

## Decision

With the `planner` label, a pull request may change the pins in a fixture pack beside a lifted mark.
The guard reports such a change as `PINNED <path>` and does not count it as another protected change.
It applies to a change when all of these hold:

- The file is a `pack.yaml` that exists already (status M), under a directory named `fixture`, `fixtures`, `test` or `tests`.
  Today that is `tests/fixtures/neutral/pack.yaml` and `tests/fixtures/slip/pack.yaml`, the fixture packs that import another pack.
  The rule covers any such file, such as those under `compiler/tests/fixtures/`, `contracts/fixtures/` and `edge/plugins/connectors/fixtures/`, once it imports a pack.
- Only lines with `sha256: <64 hex>` differ, each only in that value, and each sits in an item of the file's top-level `imports` list.
  No line comes in or goes, and the name and path of each import stay as they were.
- Each new value is the hash of the imported pack at the head of the pull request.
  The guard computes it itself from Git objects, with the definition files of the compiler (`DEFINITION`) and the canonical hash of `rezono_canon`, and refuses any other value.
  It refuses as well when a file in the imported pack is not a regular file, such as a symbolic link.
- The pull request changes the imported pack, or a pack that it imports, directly or not.
- The pull request carries the `planner` label. Without it, the change needs the label as before.

Nothing else changes: the lifted mark still follows the rules for a lift, and any other protected change beside it is still refused.

## Why the guard computes the hash

A pin is an expectation: the fixture says which pack it was made for.
A pin that the guard did not check could point a fixture at anything while a mark goes.
A pin that equals the head's own hash says nothing new, so it holds no expectation that a lift could hide.
`scripts/test_red_guard.py` checks that the guard's list of definition files equals the compiler's, so the two hashes stay the same.

## Alternatives

- **Two pull requests.** The imported pack cannot change without its pins, and the test turns green only with the change, so neither half could land alone.
- **Unprotect `pack.yaml` in fixtures.** A fixture pack's `pack.yaml` also names its own kinds and settings, which tests read as expectations.
- **Let the label allow any fixture change beside a lift.** That is the gap the rule from #708 closes.

## Not covered

- A new fixture `pack.yaml`, or a new import in one, is an ordinary protected change.
- A pin in a `pack.yaml` outside a test or fixture directory, such as `examples/subsidy/pack.yaml`, is not protected and needs no exception.
