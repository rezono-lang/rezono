"""Independent Python reference for the subsidy pack: what the rules derive, the award to the cent,
and the seal of the payment ledger.

Usage: python3 reference.py [--summary]
It writes expected/rules/<state>.json (what rules/*.dl derives), expected/calc/<state>.json (what
calc/*.yaml gives per rule and application) and expected/violations/<facts>.json, and prints a summary
per state; with --summary it only prints. State 0 is the facts; each file in scenarios/ is applied in
order, cumulatively; a record with an existing id replaces it.

It shares no code with the compiler. Money is exact: whole cents and fractions, with one rounding per
cost share, half away from zero. A parameter is the row valid on the evaluation date
(valid_from <= date < valid_until). Standard library only.
"""
import datetime
import hashlib
import json
import pathlib
import sys
from fractions import Fraction

HERE = pathlib.Path(__file__).parent
AS_OF = "2026-11-10"  # calc/award.yaml, as_of.valid_at
# Arrows per kind: the references a fact file must be able to follow.
ARROWS = {"scheme_parameter": ("article", "decision", "calendar"), "evaluation_day": ("calendar",),
          "cost_item": ("article",), "application": ("household",),
          "cost_line": ("application", "item"), "income_statement": ("household",), "advice_report": ("household",),
          "ledger_payment": ("application",), "credential_claim": ("credential",),
          "status_lookup": ("credential", "statement")}
TARGET = {"item": "cost_item", "statement": "identity_statement"}  # an arrow whose name is not its target kind
HERE_NODE = "https://municipality.invented.example"  # the municipality's own node (rules/credentials.dl)


def load(path, t):
    """One record per line, as JSON, under a line that names its kind. A record with an id that is
    already there replaces it."""
    kind = None
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        if not line.startswith(" "):
            kind = line.strip()[:-1]
            t.setdefault(kind, {})
            continue
        row = json.loads(line.strip()[2:])
        t[kind][row["id"]] = row
    return t


def states():
    """The fact states in order: the facts together, named after the first fact file, then each scenario."""
    t = {}
    # A sidecar (<file>.sources.yaml) says where a fact file's records come from; it holds no facts.
    files = sorted(f for f in (HERE / "facts").glob("*.yaml") if not f.name.endswith(".sources.yaml"))
    for f in files:
        load(f, t)
    yield f"0-{files[0].stem}", t
    for f in sorted((HERE / "scenarios").glob("*.yaml")):
        load(f, t)
        yield f.stem, t


# --- The seal of the ledger ----------------------------------------------------------

def row_hash(payment):
    """The canonical hash of a ledger payment's row: per table ledger_payment__<slot> its values as
    text, sorted; canonical JSON has sorted keys and no whitespace."""
    row = {f"ledger_payment__{s}": [str(payment[s])] for s in ("application", "booked_on", "amount")}
    return hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def seal(t):
    """Refused payments (payment, close) and the accepted ones. A close applies to a payment when it closes
    the payment's booking date or names the payment, and refuses it unless it names it with the hash of
    its row as it is now. Each close on its own."""
    refused = set()
    for p in t["ledger_payment"].values():
        for c in t.get("period_close", {}).values():
            named = [x for x in c.get("covers", []) if x["element"] == p["id"]]
            if (p["booked_on"] < c["closed_until"] or named) and {"element": p["id"], "sha256": row_hash(p)} not in named:
                refused.add((p["id"], c["id"]))
    return refused, set(t["ledger_payment"]) - {p for p, _ in refused}


# --- What the rules derive -------------------------------------------------------------------------

def lines(t, a):
    return [l for l in t["cost_line"].values() if l["application"] == a]


def quoted_costs(t, a):
    """The total of the quote lines, or None without a quote: unknown is not zero."""
    return sum(l["amount"] for l in lines(t, a)) if lines(t, a) else None


def eligible_costs(t, a):
    if not lines(t, a):
        return None
    return sum(l["amount"] for l in lines(t, a) if t["cost_item"][l["item"]]["eligibility"] == "eligible")


def statements(t, h):
    return [s for s in t["income_statement"].values() if s["household"] == h]


def reasons(t, a):
    """Why an application cannot be assessed; empty when it can."""
    out = []
    if not statements(t, t["application"][a]["household"]):
        out.append("income_statement_not_received")
    if not lines(t, a):
        out.append("quote_not_received")
    return out


def advised(t, a):
    return any(r["household"] == t["application"][a]["household"] for r in t["advice_report"].values())


def ledger_paid(t):
    """Per application the total of its accepted ledger payments."""
    accepted = seal(t)[1]
    paid = {}
    for p in t["ledger_payment"].values():
        if p["id"] in accepted:
            paid[p["application"]] = paid.get(p["application"], 0) + p["amount"]
    return paid


def in_force(t, d, day):
    """Whether a decision is in force on a day (a whole number YYYYMMDD), as std-decision defines it: it
    took effect (not proposed, first day on or before the day), has not ended, and no decision that took
    effect supersedes it."""
    def took_effect(x):
        return x["state"] != "proposed" and "valid_from_day" in x and x["valid_from_day"] <= day
    ended = "valid_until_day" in d and d["valid_until_day"] <= day
    replaced = any(d["id"] in s.get("supersedes", []) and took_effect(s) for s in t["decision"].values())
    return took_effect(d) and not ended and not replaced


def reference_dates(t):
    """The reference dates: an evaluation day is one (EvaluationDay is_a ReferenceDate), never a second day."""
    return {**t.get("reference_date", {}), **t.get("evaluation_day", {})}


def day(text):
    """A date written YYYY-MM-DD, or a whole number written YYYYMMDD, as a date."""
    text = str(text)
    return datetime.date.fromisoformat(text if "-" in text else f"{text[:4]}-{text[4:6]}-{text[6:]}")


def standing(t):
    """How each scheme parameter stands on each evaluation day of its calendar, as std-time defines it, from
    the dates themselves (not from a day count): a parameter is valid from valid_from up to, and not
    including, valid_until; an end within the horizon of the day asks for attention."""
    out = {"begun_at": [], "ended_at": [], "holds_at": [], "judgement": [], "interval_inverted": []}
    for p in t["scheme_parameter"].values():
        s, e = day(p["valid_from"]), day(p["valid_until"])
        if e <= s:
            out["interval_inverted"].append([p["id"]])
        for r in t.get("evaluation_day", {}).values():
            if r["calendar"] != p["calendar"]:
                continue
            at, near = day(r["day"]), day(r["day"]) + datetime.timedelta(days=r["horizon"])
            pair = [p["id"], r["id"]]
            if s <= at:
                out["begun_at"].append(pair)
            if e <= at:
                out["ended_at"].append(pair)
                out["judgement"].append(pair + ["negative", "ended"])
            if s <= at < e:
                out["holds_at"].append(pair)
                out["judgement"].append(pair + (["attention", "end_within_horizon"] if e <= near
                                                else ["positive", "end_beyond_horizon"]))
            if at < s and at < e:
                out["judgement"].append(pair + ["not_begun", "start_ahead"])
    return out


def claim_reasons(t, k):
    """Why a claim of another issuer does not hold; empty when it does. It holds when the holder disclosed it,
    a trust entry let its issuer state its attribute on the day of issuance (from inclusive, until exclusive),
    and a status lookup found its credential valid while none found it revoked or suspended."""
    claim = t["credential_claim"][k]
    c = t["credential"][claim["credential"]]
    out = []
    if "value" not in claim:
        out.append("not_disclosed")
    if not may_state(t, c["issuer"], claim["attribute"], c["issued_on_day"]):
        out.append("issuer_not_authorised")
    if not good_standing(t, "credential", c["id"]):
        out.append("status_not_valid")
    return out


def may_state(t, issuer, attribute, day):
    """A trust entry lets the issuer state the attribute on that day (from inclusive, until exclusive)."""
    return any(e["issuer"] == issuer and e["attribute"] == attribute and e["valid_from_day"] <= day < e["valid_until_day"]
               for e in t["trust_entry"].values())


def good_standing(t, field, rid):
    """A status lookup found the credential or statement valid, and none found it revoked or suspended."""
    found = {s["status"] for s in t["status_lookup"].values() if s.get(field) == rid}
    return "valid" in found and not found & {"revoked", "suspended"}


def names_node(t, s, node, until):
    """A trust entry lets the statement's issuer name identifiers of `node`: from its first day up to and
    including the day the issuer states, and `until(entry)` holds. An entry without a node names none."""
    return any(e["issuer"] == s["issuer"] and e["attribute"] == "same_subject" and e.get("node") == node
               and e["valid_from_day"] <= s["issued_on_day"] < e["valid_until_day"] and until(e)
               for e in t["trust_entry"].values())


def statement_reasons(t, s):
    """Why an identity statement does not hold; empty when it does. Authorised: for each node it names, an entry of
    its issuer names that node, and on the day of one lookup of the statement by the node both entries' windows hold
    the issuer's day and that lookup day (from <= issued <= looked up < until). Scoped but no lookup inside the
    windows: its issuance is not established. And a status lookup found it in good standing."""
    out = []
    nodes = (s["first_node"], s["second_node"])
    days = sorted({lk["looked_up_on_day"] for lk in t["status_lookup"].values() if lk.get("statement") == s["id"]})
    scoped = all(names_node(t, s, n, lambda e: True) for n in nodes)
    covered = any(all(names_node(t, s, n, lambda e, d=d: s["issued_on_day"] <= d < e["valid_until_day"]) for n in nodes)
                  for d in days)
    if not scoped:
        out.append("statement_issuer_not_authorised")
    elif days and not covered:
        out.append("statement_issuance_not_established")
    if not good_standing(t, "statement", s["id"]):
        out.append("statement_status_not_valid")
    return out


def both_ways(s):
    """The two identifiers a statement names, as (node, identifier, other node, other identifier), both ways."""
    first, second = (s["first_node"], s["first_identifier"]), (s["second_node"], s["second_identifier"])
    return [first + second, second + first]


def identification(t, c):
    """The municipality's identifiers for a credential's subject, and the reasons it has none: a statement names
    the subject (the issuer's node and identifier, both) beside an identifier of the municipality's node."""
    naming = [(s, p) for s in t["identity_statement"].values() for n, x, m, p in both_ways(s)
              if (n, x, m) == (c["issuer"], c["subject"], HERE_NODE)]
    known = {p for s, p in naming if not statement_reasons(t, s)}
    if known or not naming:
        return known, [] if known else ["no_identity_statement"]
    return known, sorted({r for s, _ in naming for r in statement_reasons(t, s)})


def rules(t):
    """What rules/*.dl derive: sets as sorted lists, integers as decimal text. Only the relations a
    reader acts on; the read rules are checked through the publisher (test_subsidy.py)."""
    for kind in ("trust_entry", "credential", "credential_claim", "identity_statement", "status_lookup"):
        t.setdefault(kind, {})
    apps = sorted(t["application"])
    household = {a: t["application"][a]["household"] for a in apps}
    count = {h: sum(1 for a in apps if household[a] == h) for h in t["household"]}
    known = [a for a in apps if not reasons(t, a)]
    out = {
        "quoted_costs": [[a, str(quoted_costs(t, a))] for a in apps if lines(t, a)],
        "eligible_costs": [[a, str(eligible_costs(t, a))] for a in apps if lines(t, a)],
        "costs_mismatch": [[a, str(t["application"][a]["claimed_costs"]), str(quoted_costs(t, a))] for a in apps
                           if lines(t, a) and t["application"][a]["claimed_costs"] != quoted_costs(t, a)],
        "quote_missing": [[a] for a in apps if not lines(t, a)],
        "income_not_received": [[a, household[a]] for a in apps if not statements(t, household[a])],
        "assessment": [[a, "unknown", r] for a in apps for r in reasons(t, a)] + [[a, "known", ""] for a in known],
        "assessed_income": [[a, str(s["income"])] for a in known for s in statements(t, household[a])],
        "assessed_costs": [[a, str(eligible_costs(t, a))] for a in known],
        "advised": [[a] for a in apps if advised(t, a)],
        "repeat_application": [[h, str(n)] for h, n in count.items() if n >= 2],
    }
    # The scheme: a parameter stands on its decision when that decision is in force on the reference date.
    decided = [[p["id"], p["decision"], r["id"]] for p in t["scheme_parameter"].values()
               for r in reference_dates(t).values() if in_force(t, t["decision"][p["decision"]], r["day"])]
    out["decided_parameter"] = decided
    out["undecided_parameter"] = [[p, r] for p in t["scheme_parameter"] for r in reference_dates(t)
                                  if not any(x[0] == p and x[2] == r for x in decided)]
    # std-time, read through views.yaml: how each parameter stands on the evaluation day.
    out.update(standing(t))
    # The ledger: what it paid per application, and the seal's own relations, refused and accepted.
    refused, accepted = seal(t)
    out["ledger_paid"] = [[a, str(c)] for a, c in ledger_paid(t).items()]
    out["ledger_payment__refused"] = [[p, c] for p, c in refused]
    out["ledger_payment__accepted"] = [[p] for p in accepted]
    # What other organisations state (rules/credentials.dl): one outcome per claim, and what holds.
    claims = {k: claim_reasons(t, k) for k in t["credential_claim"]}
    out["claim_assessment"] = ([[k, "unknown", r] for k, rs in claims.items() for r in rs]
                               + [[k, "known", ""] for k, rs in claims.items() if not rs])
    credential = t["credential"]
    out["attested"] = [[credential[c["credential"]]["issuer"], credential[c["credential"]]["subject"], c["attribute"],
                        c["value"]] for k, c in t["credential_claim"].items() if not claims[k]]
    # Identity across nodes: only a statement that holds joins two identifiers; equal ones join nothing.
    out["same_subject"] = [list(pair) for s in t["identity_statement"].values() if not statement_reasons(t, s)
                           for pair in both_ways(s)]
    identified = {c: identification(t, credential[c]) for c in credential}
    out["subject_identification"] = ([[c, "unknown", r] for c, (_, rs) in identified.items() for r in rs]
                                     + [[c, "known", ""] for c, (ps, _) in identified.items() if ps])
    out["attested_here"] = [list(r) for r in {(p, a, v) for c, (ps, _) in identified.items() for p in ps
                                              for n, x, a, v in out["attested"]
                                              if (n, x) == (credential[c]["issuer"], credential[c]["subject"])}]
    out["status_lookup_not_of_one"] = [[s["id"]] for s in t["status_lookup"].values()
                                       if ("credential" in s) == ("statement" in s)]
    # A finding on two calculation results (rules/findings.dl of the scheme): where the maximum of article 7
    # cut in. Only known values are facts for a rule, so an unknown award is never in it.
    steps = {a: award(t, a) for a in apps}
    out["maximum_applied"] = [[a, str(s["entitlement"]), str(s["award"])] for a, s in steps.items()
                              if s["award"] != "unknown" and s["award"] < s["entitlement"]]
    return {k: sorted(v) for k, v in out.items()}


# --- The award, exactly ----------------------------------------------------------------------------

def parameter(t, name, on):
    """The value of the parameter row valid on the date. Every parameter of this pack has exactly one such
    row in every state; anything else stops the reference rather than guessing a value."""
    rows = [r for r in t["scheme_parameter"].values() if r["name"] == name and r["valid_from"] <= on < r["valid_until"]]
    assert len(rows) == 1, (name, on, rows)
    return rows[0]["value"]


def half_away(x):
    """Round a fraction to a whole number, half away from zero."""
    x = Fraction(x)
    n = (abs(x) + Fraction(1, 2)).__floor__()
    return n if x >= 0 else -n


def award(t, a, on=AS_OF):
    """Every step of the award for one application: a whole number of cents, or the state `unknown`."""
    household = t["household"][t["application"][a]["household"]]
    threshold = parameter(t, "income_threshold_base", on) + household["persons"] * parameter(t, "income_threshold_per_person", on)
    limit = threshold + parameter(t, "income_margin", on)
    out = {"income_threshold": threshold, "income_limit": limit}
    if reasons(t, a):
        # No income or no costs: no cost share. Without advice the allowance is nothing whatever the
        # share; with advice it depends on the share, so it is unknown too.
        out.update(cost_share="unknown", advice_allowance="unknown" if advised(t, a) else 0,
                   entitlement="unknown", award="unknown")
        return out
    incomes = {s["income"] for s in statements(t, t["application"][a]["household"])}
    assert len(incomes) == 1, (a, incomes)  # two different statements would make the income invalid
    income, costs = incomes.pop(), eligible_costs(t, a)
    if income <= threshold:
        share = half_away(Fraction(costs * parameter(t, "full_rate", on), 1_000_000))
    elif income <= limit:
        share = half_away(Fraction(costs * parameter(t, "partial_rate", on), 1_000_000))
    else:
        share = 0
    allowance = parameter(t, "advice_allowance", on) if advised(t, a) and share > 0 else 0
    out.update(cost_share=share, advice_allowance=allowance, entitlement=share + allowance,
               award=min(share + allowance, parameter(t, "maximum_award", on)))
    return out


def calc(t, on=AS_OF):
    """What calc/*.yaml gives: per rule and application the value as decimal text, or its state."""
    out = {}
    paid = ledger_paid(t)
    for a in sorted(t["application"]):
        steps = award(t, a, on)
        # Drift against the ledger: what was paid minus the award. Not applicable without a payment;
        # unknown when the award is, never a difference against zero.
        steps["payment_difference"] = ("not_applicable" if a not in paid else
                                       "unknown" if steps["award"] == "unknown" else paid[a] - steps["award"])
        for rule, value in steps.items():
            out.setdefault(rule, {})[a] = str(value)
    return out


# --- A fact file on its own ------------------------------------------------------------------------

def dangling(path):
    """The reference violations of one fact file loaded on its own: an arrow to an element that another
    file holds. Together the facts have none."""
    t = load(path, {})
    out = {}
    for kind, arrows in ARROWS.items():
        for arrow in arrows:
            rows = sorted([r["id"], r[arrow]] for r in t.get(kind, {}).values()
                          if arrow in r and r[arrow] not in t.get(TARGET.get(arrow, arrow), {}))
            if rows:
                out[f"{kind}__{arrow}__reference"] = rows
    return out


def compact(doc):
    """JSON with one row per line: a reader can diff it, and a whole population stays a small file."""
    parts = []
    for key in sorted(doc):
        rows = ",\n".join("  " + json.dumps(r, ensure_ascii=False) for r in doc[key])
        parts.append(f' {json.dumps(key)}: [\n{rows}\n ]' if rows else f' {json.dumps(key)}: []')
    return "{\n" + ",\n".join(parts) + "\n}\n" if parts else "{}\n"


def write(path, text):
    if "--summary" in sys.argv:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def main():
    for f in sorted(f for f in (HERE / "facts").glob("*.yaml") if not f.name.endswith(".sources.yaml")):
        write(HERE / "expected" / "violations" / f"{f.stem}.json", compact(dangling(f)))
    for label, t in states():
        derived = rules(t)
        write(HERE / "expected" / "rules" / f"{label}.json", compact(derived))
        summary = {"applications": len(t["application"]),
                   "unknown": len({a for a, s, _ in derived["assessment"] if s == "unknown"}),
                   "mismatch": len(derived["costs_mismatch"]), "repeat": len(derived["repeat_application"]),
                   "undecided": len(derived["undecided_parameter"])}
        values = calc(t)
        # The form of examples/test_examples.py (golden_text): the test compares the bytes.
        write(HERE / "expected" / "calc" / f"{label}.json", json.dumps(values, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
        awards = [int(v) for v in values["award"].values() if v != "unknown"]
        summary.update(awarded=sum(1 for v in awards if v > 0), total_cents=sum(awards))
        drift = [int(v) for v in values["payment_difference"].values() if v not in ("unknown", "not_applicable", "0")]
        summary.update(paid=sum(1 for v in values["payment_difference"].values() if v != "not_applicable"),
                       drift=len(drift), drift_cents=sum(drift), refused=len(derived["ledger_payment__refused"]))
        print(label, summary)


if __name__ == "__main__":
    main()
