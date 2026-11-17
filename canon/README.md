# rede-canon

The canonical JSON form and hash of Rede, for Python (compiler, checker and edge). The rule is in [docs/contracts.md](../docs/contracts.md#canonical-hash); its TypeScript twin is [viewer/src/lib/canon.ts](../viewer/src/lib/canon.ts).

```python
from rede_canon import canonical_json, canonical_sha256, sha256_hex

canonical_json({"b": 2**64, "a": "één"})  # '{"a":"één","b":"18446744073709551616"}'
canonical_sha256({"seed": 1})             # the hash of a value
sha256_hex(path.read_bytes())             # the hash of a file
```

A value without a canonical form (a float, `null`, a datetime without a time zone) raises `CanonError`, with a `code` as in the test vectors.

```bash
scripts/install-python.sh requirements/dev.txt canon
cd canon && pytest -q   # the test vectors in contracts/fixtures/canon/, and RFC 8785 as an oracle
```
