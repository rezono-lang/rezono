"""The rank: one chosen proof per conclusion (docs/formal.md §3). The one selector of the explainer and the publisher.

The input is the AND/OR graph of rule instances: each instance is a conclusion, the derived positive
premises it needs, and a tie-break key. A conclusion is an OR over its instances; an instance is an AND over
its premises. Base premises, negations and aggregates are not inputs here: a caller passes only instances
whose other premises already hold for it (all of them for the explainer, the usable ones for a role).

The rank of an instance without derived premises is 1; otherwise one more than the highest rank of the
chosen proofs of its premises. Each conclusion gets the instance of least (rank, tie-break, position). This
is proof depth, not the number of steps: two premises of rank 3 give rank 4. An instance whose premise has no
chosen proof is never chosen, so the result is the least fixpoint and every chosen proof is acyclic.

The checker does not use this: it checks the chosen proofs on its own (formal.md §11).
"""

from __future__ import annotations

import heapq
from collections import defaultdict
from collections.abc import Hashable, Iterable, Sequence


def choose(instances: Sequence[tuple[Hashable, Iterable[Hashable], tuple]]) -> dict[Hashable, tuple[int, int]]:
    """Every derivable conclusion with (rank, position in `instances`) of its chosen instance.

    `instances` are (conclusion, derived positive premises, tie-break key). Equal rank goes to the least
    tie-break key, then the earliest position, so the choice depends only on the input.
    """
    users = defaultdict(list)
    remaining, deepest, heap = [], [], []
    for i, (_, needs, tie) in enumerate(instances):
        needs = set(needs)
        remaining.append(len(needs))
        deepest.append(0)
        for p in needs:
            users[p].append(i)
        if not needs:
            heapq.heappush(heap, (1, tie, i))
    chosen = {}
    while heap:
        rank, _, i = heapq.heappop(heap)
        head = instances[i][0]
        if head in chosen:
            continue
        chosen[head] = (rank, i)
        for j in users[head]:
            remaining[j] -= 1
            deepest[j] = max(deepest[j], rank)
            if remaining[j] == 0:
                heapq.heappush(heap, (deepest[j] + 1, instances[j][2], j))
    return chosen
