"""Neutral operation cases for the library example and for packs drawn by genpack."""

import yaml

from rezono_compiler import operate


def rename(subject, old, new, **scope):
    return ({"op": "rename", **scope, subject: old, "to": new},
            {"op": "rename", **scope, subject: new, "to": old}, subject)


RENAMES = [
    rename("kind", "Copy", "Item"),
    rename("slot", "title", "caption", kind="Work"),
    rename("enum", "MembershipType", "Status"),
    rename("value", "youth", "junior", enum="MembershipType"),
]


def move(kind, slot, to, **options):
    return {"op": "move", "kind": kind, "slot": slot, "to": to, **options}


# The two member records share Person with a staff record. Copies 1001 and
# 1002 point to w1, while 1003 points to w2: both work titles have a destination.
MOVES = [
    (move("Member", "home_branch", "Person"), move("Person", "home_branch", "Member"), True, ("member__home_branch",)),
    (move("Person", "name", "Member", accept_loss=True), None, False, ("person__name",)),
    (move("Work", "title", "Copy", via="Copy.work"), move("Copy", "title", "Work", via="Copy.work"),
     True, ("work__title",)),
]
# The public library OperationSet splits Member and combines Branch and its embedded Address.
SPLIT = {"op": "split_by", "kind": "Member", "slot": "membership",
         "cases": [{"value": "adult", "kind": "AdultMember"}, {"value": "youth", "kind": "YouthMember"}]}
COMBINE = {"op": "combine", "kind": "Branch", "absorb": "Address", "via": "Branch.address"}
DROPS = [({"op": "drop", "kind": "Copy", "slot": "reference_only", "accept_loss": True}, "copy__reference_only")]


def files(directory):
    return {p.relative_to(directory).as_posix(): p.read_bytes() for p in directory.rglob("*") if p.is_file()}


def run(directory, operations, work, name="forward"):
    spec = work / f"{name}.yaml"
    out = work / name
    meta = yaml.safe_load((directory / "pack.yaml").read_text(encoding="utf-8"))
    doc = {"format": "rezono.operations/1", "pack": meta["name"], "operations": operations}
    spec.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8", newline="\n")
    return operate.operate(directory, spec, out), out


def move_ops(pack):
    candidates = []
    for kind in pack.kinds.values():
        if kind.parent:
            parent = pack.kinds[kind.parent]
            candidates.extend(move(kind.cls, slot, parent.cls) for slot in kind.slots)
            candidates.extend(move(parent.cls, slot, kind.cls, accept_loss=True) for slot in parent.slots)
        for arrow in kind.slots.values():
            if not arrow.arrow or arrow.multivalued or arrow.range == kind.name:
                continue
            other = pack.kinds[arrow.range]
            via = f"{kind.cls}.{arrow.name}"
            candidates.extend(move(other.cls, slot, kind.cls, via=via, accept_loss=True) for slot in other.slots)
            candidates.extend(move(kind.cls, slot, other.cls, via=via, accept_loss=True)
                              for slot in kind.slots if slot != arrow.name)
    return candidates


def split_ops(pack):
    candidates = []
    for kind in pack.kinds.values():
        for slot in kind.slots.values():
            if slot.enum and not slot.multivalued:
                cases = [{"value": value, "kind": f"Case{i}"} for i, value in enumerate(pack.enums[slot.enum])]
                candidates.append({"op": "split_by", "kind": kind.cls, "slot": slot.name, "cases": cases})
    return candidates


def combine_ops(pack):
    candidates = []
    for kind in pack.kinds.values():
        for arrow in kind.slots.values():
            if arrow.arrow and not arrow.multivalued and arrow.range != kind.name:
                other = pack.kinds[arrow.range]
                via = f"{kind.cls}.{arrow.name}"
                for keeper, absorbed in ((kind, other), (other, kind)):
                    candidates.append({"op": "combine", "kind": keeper.cls, "absorb": absorbed.cls,
                                       "via": via, "accept_loss": True})
    return candidates
