"""Writes the synthetic population of the subsidy pack, and the payment ledger that goes with it.

Usage: python3 generate.py [pack directory, default this one]
It writes population.yaml (households, applications, quote lines, income statements and advice reports),
ledger.yaml (the payments of October 2026 as the finance department's ledger records them) and, next to
facts/, scenarios/2-close-october.yaml (the close of that month, naming every payment with its row hash).
Nothing here is a real household: every row comes from the generator below, with a fixed seed, so
every run on every machine gives the same bytes (test_subsidy.py checks that).

Together with the seven applications written by hand (facts/applications.yaml) the population is 240
applications. The generator has no random-number library: `random` may change between Python versions,
so it carries its own small generator (splitmix64). Standard library only.
"""
import json
import pathlib
import sys

import reference

HERE = pathlib.Path(__file__).parent
SEED = 20261110
APPLICATIONS = 240
SECOND_APPLICATIONS = 6    # households that apply twice
WITHOUT_STATEMENT = 13     # households whose income statement has not been received
WITHOUT_QUOTE = 2          # applications whose quote has not been received
MASK = (1 << 64) - 1

# The eligible measures a quote can name: (cost item, weight, lowest and highest price in euros).
MEASURES = (("heat-pump", 30, 6500, 14000), ("roof-insulation", 20, 1800, 6200), ("wall-insulation", 15, 1500, 4800),
            ("floor-insulation", 12, 1200, 3500), ("insulating-glazing", 15, 2000, 7000), ("solar-boiler", 8, 2500, 4500))
NEEDS_SCAFFOLDING = {"roof-insulation", "wall-insulation", "insulating-glazing", "solar-boiler"}
# The payment runs of October 2026, and what the ledger holds for the applications written by hand:
# A002 in two instalments, A003 paid before its income statement was in, A007 without the allowance.
RUNS = ("2026-10-06", "2026-10-13", "2026-10-20", "2026-10-27")
PAID_BY_HAND = (("A001", "2026-10-06", 269400), ("A002", "2026-10-06", 100000), ("A002", "2026-10-13", 66000),
                ("A003", "2026-10-13", 131020), ("A004", "2026-10-13", 500000), ("A007", "2026-10-20", 128000))


class Rng:
    """splitmix64: a few lines, the same numbers everywhere."""

    def __init__(self, seed):
        self.state = seed

    def next(self):
        self.state = (self.state + 0x9E3779B97F4A7C15) & MASK
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK
        return z ^ (z >> 31)

    def between(self, low, high):
        return low + self.next() % (high - low + 1)

    def chance(self, percent):
        return self.next() % 100 < percent

    def pick(self, weighted):
        """One value of [(value, weight)], by weight."""
        n = self.next() % sum(w for _, w in weighted)
        for value, weight in weighted:
            if n < weight:
                return value
            n -= weight

    def shuffled(self, items):
        items = list(items)
        for i in range(len(items) - 1, 0, -1):
            j = self.next() % (i + 1)
            items[i], items[j] = items[j], items[i]
        return items


def price(rng, low, high):
    """A quoted price in cents: most quotes are round, some are to the cent."""
    if rng.chance(60):
        return rng.between(low // 50, high // 50) * 5000
    return rng.between(low * 100, high * 100)


def population(t):
    """Adds the generated households and their applications to the facts written by hand."""
    rng = Rng(SEED)
    by_hand = len(t["application"])
    n_households = APPLICATIONS - by_hand - SECOND_APPLICATIONS
    first = len(t["household"]) + 1
    households = [f"H{first + i:03d}" for i in range(n_households)]
    # Incomes are spread around the threshold of article 4, read from the scheme's own parameters.
    # This only shapes the data: the award is computed from the facts, never from here.
    base, per_person = (reference.parameter(t, name, reference.AS_OF) // 100 for name in
                        ("income_threshold_base", "income_threshold_per_person"))
    for h in households:
        persons = rng.pick([(1, 28), (2, 32), (3, 16), (4, 16), (5, 8)])
        threshold = base + persons * per_person
        # Two draws added up: most incomes lie near the threshold, few far below it or far above the limit.
        income = max(12000, threshold + rng.between(-9000, 9000) + rng.between(-7000, 13000))
        t["household"][h] = {"id": h, "persons": persons, "_income": income * 100, "_advised": rng.chance(35)}
    without_statement = set(rng.shuffled(households)[:WITHOUT_STATEMENT])
    for h in households:
        row = t["household"][h]
        income, was_advised = row.pop("_income"), row.pop("_advised")
        if h not in without_statement:
            s = f"S{len(t['income_statement']) + 1:03d}"
            t["income_statement"][s] = {"id": s, "household": h, "income": income}
        if was_advised:
            r = f"R{len(t['advice_report']) + 1:03d}"
            t["advice_report"][r] = {"id": r, "household": h}
    # Applications arrive in an order that says nothing about the household's number.
    filing = rng.shuffled(households + rng.shuffled(households)[:SECOND_APPLICATIONS])
    without_quote = set(rng.shuffled(range(len(filing)))[:WITHOUT_QUOTE])
    for n, h in enumerate(filing):
        a = f"A{by_hand + n + 1:03d}"
        claimed = 0
        if n not in without_quote:
            count = rng.pick([(1, 50), (2, 35), (3, 15)])
            items = []
            while len(items) < count:
                item = rng.pick([(m, w) for m, w, _, _ in MEASURES if m not in items])
                items.append(item)
            quote = [(m, price(rng, low, high)) for m, _, low, high in MEASURES if m in items]
            if NEEDS_SCAFFOLDING & set(items) and rng.chance(30):
                quote.append(("scaffolding", price(rng, 250, 900)))
            for item, amount in quote:
                l = f"L{len(t['cost_line']) + 1:04d}"
                t["cost_line"][l] = {"id": l, "application": a, "item": item, "amount": amount}
                claimed += amount
        else:
            claimed = price(rng, 2000, 9000)
        t["application"][a] = {"id": a, "household": h, "claimed_costs": claimed}
    return rng


def ledger(t, rng):
    """The October ledger: what the finance department paid. It follows the awards, as another system
    computed them, with the differences a ledger has: an instalment, an old rate, a payment made twice."""
    awards = {a: reference.award(t, a) for a in sorted(t["application"])}
    by_hand = {a for a, _, _ in PAID_BY_HAND}
    due = [a for a, v in awards.items() if a not in by_hand and v["award"] != "unknown" and v["award"] > 0 and rng.chance(40)]
    old_rate = next(a for a in due if is_partial(t, a, awards[a]))
    twice = next(a for a in reversed(due) if a != old_rate)
    rows = list(PAID_BY_HAND)
    for a in due:
        day = RUNS[rng.next() % len(RUNS)]
        amount = awards[a]["award"]
        if a == old_rate:
            # Paid at the partial rate of before 1 July 2026.
            old = reference.award(t, a, on="2026-06-30")
            rows.append((a, day, old["award"]))
        elif a == twice:
            rows += [(a, day, amount), (a, RUNS[-1], amount)]
        elif amount > 200000 and rng.chance(12):
            first = amount // 2
            rows += [(a, day, first), (a, RUNS[-1], amount - first)]
        else:
            rows.append((a, day, amount))
    rows.sort(key=lambda r: (r[1], r[0], -r[2]))
    return {f"P{n:03d}": {"id": f"P{n:03d}", "application": a, "booked_on": day, "amount": amount}
            for n, (a, day, amount) in enumerate(rows, 1)}


def is_partial(t, a, steps):
    """Whether the partial rate gave this cost share: the old rate then gives another amount."""
    return steps["cost_share"] > 0 and reference.award(t, a, on="2026-06-30")["award"] != steps["award"]


def write(path, header, kinds):
    """A fact file: a header of comments, then per kind one record per line, as JSON, sorted by id."""
    out = [f"# {line}" for line in header]
    for kind, rows in kinds:
        out.append(f"{kind}:")
        out += [f"  - {json.dumps(rows[k], ensure_ascii=False)}" for k in sorted(rows)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


def main(root):
    t = {}
    for f in ("scheme.yaml", "applications.yaml"):
        reference.load(HERE / "facts" / f, t)
    by_hand = {kind: set(rows) for kind, rows in t.items()}
    rng = population(t)
    new = {kind: {k: v for k, v in rows.items() if k not in by_hand[kind]} for kind, rows in t.items()}
    write(root / "facts" / "population.yaml",
          [f"The synthetic population: generated by generate.py (seed {SEED}); do not edit.",
           f"No real household. Together with facts/applications.yaml: {APPLICATIONS} applications."],
          [(k, new[k]) for k in ("household", "application", "cost_line", "income_statement", "advice_report")])
    payments = ledger(t, rng)
    write(root / "facts" / "ledger.yaml",
          ["The payment ledger of October 2026, as the finance department records it: a reference source.",
           f"Synthetic: generated by generate.py (seed {SEED}); do not edit."],
          [("ledger_payment", payments)])
    # The close of October: every payment of the month with the hash of its row. The hash here is the
    # reference's own; test_subsidy.py holds the file equal to what `rede_compiler close` writes.
    close = {"id": "october-2026", "closed_until": "2026-11-01",
             "covers": [{"element": p, "sha256": reference.row_hash(payments[p])} for p in sorted(payments)]}
    write(root / "scenarios" / "2-close-october.yaml",
          ["The finance department closes October (closed_until 1 November 2026). The close names every payment",
           "of the month with the hash of its row, as this command writes it:",
           "  python -m rede_compiler close examples/subsidy --close october-2026 --until 2026-11-01 --file facts/ledger.yaml",
           "Nothing is refused, so no outcome changes. Generated by generate.py with the ledger; do not edit."],
          [("period_close", {close["id"]: close})])


if __name__ == "__main__":
    main(pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else HERE)
