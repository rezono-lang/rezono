"""The scaling check of the profile (docs/gui.md, Work per request: O(page)).

  python deploy/profiles/edge/scale.py RESULTS PACK COPY

RESULTS is profile.mjs's results.json; PACK the pack's name, COPY the name of its copy with the facts multiplied
(multiply.py). Every path of PACK (`/PACK` or `/PACK/...`) is paired with the same path of COPY. A pair passes
only if both answered 200 with every measure, and the copy's page:
- reads no object of the store that is larger on the copy: every object read outside the published views (a
  manifest, a bundle, a snapshot, a witness file) is compared with the same object of the pack, and may not be
  more than 1.5 times its size plus 1 KiB. A view piece (a tile, a row or proof tree's leaf or page, an index)
  is bounded at publication, so only its count is compared;
- reads at most 1.75 times as many objects plus 4 (a tree grows a level by the logarithm of the data), makes at
  most 2 more GATE calls, gets at most 1.5 times the GATE bytes plus 16 KiB, lists at most 8 more keys.
A control pair (`control:PACK`, `control:COPY`: a whole snapshot read straight from the gate) must measure
growth of the same snapshot. If it does not, the check cannot distinguish a page read from a full snapshot
read and fails. CPU and heap are shown, not checked. Prints a Markdown table; exit 1 on growth or a missing measure.
"""

from __future__ import annotations

import json
import sys

MEASURES = ("gate_calls", "gate_bytes", "store_gets", "store_bytes", "store_listed", "store_reads")
COUNTED = {"gate_calls": (1.0, 2), "gate_bytes": (1.5, 16 * 1024), "store_gets": (1.75, 4), "store_listed": (1.0, 8)}
OBJECT = (1.5, 1024)
SHOWN = ("viewer_cpu_ms", "viewer_heap_after_mb")


def bounded(key: str) -> bool:
    """A piece made at publication, bounded in size by its contract: anything under a role's views."""
    return "/views/" in key


def object_grew(original: int, measured: int) -> bool:
    return measured > original * OBJECT[0] + OBJECT[1]


def objects(pack: str, copy: str, base_reads: dict, reads: list) -> list[str]:
    """The objects the copy read that are larger than the same object of the pack (or that the pack never read)."""
    out = []
    for key, size in reads:
        if bounded(key):
            continue
        twin = pack + key[len(copy):] if key.startswith(f"{copy}/") else key
        if twin not in base_reads:
            out.append(f"{key}: read on {copy}, never on {pack}")
        elif object_grew(base_reads[twin], size):
            out.append(f"{key}: {base_reads[twin]} bytes on {pack}, {size} on {copy}")
    return out


def growing_snapshots(pack: str, copy: str, base: dict, grown: dict) -> int:
    if "snapshot" in base or "snapshot" in grown:
        # A changed snapshot has a new content-addressed store key. The request records its relation.
        relation = base.get("snapshot")
        if not isinstance(relation, str) or not relation or relation != grown.get("snapshot"):
            return 0
        return int(object_grew(base["gate_bytes"], grown["gate_bytes"]))

    # Older profiles can prove growth only for matching keys read by the controls themselves.
    baseline = {key.removeprefix(f"{pack}/"): size for key, size in base["store_reads"]
                if key.startswith(f"{pack}/") and not bounded(key)}
    return sum(object_grew(baseline[name], size) for key, size in grown["store_reads"]
               if key.startswith(f"{copy}/") and (name := key.removeprefix(f"{copy}/")) in baseline)


def check(results: list[dict], pack: str, copy: str) -> tuple[list[str], list[str]]:
    by = {r["path"]: r for r in results}
    pairs = [(p, f"/{copy}{p[len(pack) + 1:]}") for p in by
             if p == f"/{pack}" or p.startswith((f"/{pack}/", f"/{pack}?"))]
    control_path = f"control:{pack}"
    base_paths = {path for path, _ in pairs} | {control_path}
    base_reads = {k: n for r in results if r["path"] in base_paths
                  for k, n in r.get("store_reads", []) if k.startswith(f"{pack}/")}
    rows, failures = [], []
    if not pairs:
        failures.append(f"no path of {pack} was profiled")
    for path, mirror in pairs + [(control_path, f"control:{copy}")]:
        base, grown = by.get(path), by.get(mirror)
        control = path.startswith("control:")
        if base is None or grown is None:
            failures.append(f"{mirror if base else path}: not profiled")
            continue
        missing = [f"{r['path']}: status {r.get('status')}" for r in (base, grown) if r.get("status") != 200]
        missing += [f"{r['path']}: no {m}" for r in (base, grown) for m in MEASURES if m not in r]
        if missing:
            failures += missing
            continue
        cells = []
        for m, (factor, slack) in COUNTED.items():
            limit = base[m] * factor + slack
            ok = control or grown[m] <= limit
            cells.append(f"{base[m]} → {grown[m]}" + ("" if ok else " ✗"))
            if not ok:
                failures.append(f"{path}: {m} {base[m]} on {pack}, {grown[m]} on {copy} (at most {limit:.0f})")
        if control:
            count = growing_snapshots(pack, copy, base, grown)
            cells.append(f"{count} larger (must be > 0)" + ("" if count else " ✗"))
            if not count:
                failures.append(f"{path}: no matching snapshot measured larger on {copy}: the check cannot tell")
        else:
            grew = objects(pack, copy, base_reads, grown["store_reads"])
            cells.append(f"{len(grew)} larger" + (" ✗" if grew else ""))
            failures += [f"{path}: {g}" for g in grew]
        cells += [f"{base.get(m, '–')} → {grown.get(m, '–')}" for m in SHOWN]
        rows.append(f"| `{path}` | " + " | ".join(cells) + " |")
    head = ["## Scaling check", "", f"`{pack}` against `{copy}` (its facts multiplied). ✗: grows with the data.", "",
            "| path | " + " | ".join((*COUNTED, "objects", *SHOWN)) + " |", "|---" * (2 + len(COUNTED) + len(SHOWN)) + "|"]
    return head + rows + [""] + ([f"- {f}" for f in failures] or ["No page costs more on the larger copy; the control does."]), failures


def main(argv=None) -> int:
    results, pack, copy = (argv or sys.argv[1:])[:3]
    lines, failures = check(json.loads(open(results).read()), pack, copy)
    print("\n".join(lines))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
