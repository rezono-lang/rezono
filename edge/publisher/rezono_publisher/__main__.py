"""Command line: compute one epoch of a pack on the batch backend and publish it.

  python -m rezono_publisher PACK --profile deploy/profiles/edge.yaml --epoch 1 \
      --knowledge-time 2026-11-06T12:00:00Z --source rules=<commit> [--store file:///data]

With --views, check and write the views (rezono_publisher.views) before the manifest and its head.
A view that shows more than its role reads exits 2 without exposing the new manifest.
With --forms, each filtered role's Reckon Data form (rezono_publisher.forms, RV-K16), the same way: a form that is
not what its role's files say exits 2 without exposing the new manifest. With --forms-after the manifest is
published without them and its build names the forms library all the same, so a new library publishes the pack
again; the forms follow (`python -m rezono_publisher.forms --newest`, job `forms` of promote.yml).
With --skip-unchanged, nothing is computed or written when the pack's newest main manifest was made from the
same pack and the same build (publish.unchanged): that manifest stays the newest, and its id is printed.

Exit 0: published, or unchanged (prints the manifest id). Exit 2: a red check, no new manifest. Exit 1: an error.
A filtered role of the profile that the pack's read rules give nothing is published with nothing to read, and
named in a note on stderr (RV-S10): the profile and the pack disagree about the roles.
The knowledge time comes from the caller (the time of the source commit), never from the clock.
Seconds per phase go to stderr and the CI step summary (timing.py), never into the store.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import os
import subprocess
import sys
from pathlib import Path

import yaml

from . import access, forms, publish, store, timing, views


def profile_settings(path: str) -> tuple[str | None, str | None, dict]:
    """From a deploy profile: the store URL, the S3 endpoint (from the variable it names) and the roles."""
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    s = cfg.get("storage") or {}
    url = f"s3://{s['bucket']}" if s.get("adapter") == "s3" else s.get("url")
    endpoint = os.environ.get(s["endpoint_env"]) if s.get("endpoint_env") else None
    return url, endpoint, dict((cfg.get("access") or {}).get("roles") or {})


def published(pack_dir: str, st, roles: dict, with_views: bool, with_forms: bool = False) -> dict | None:
    """The pack's newest main manifest, if it was made from the pack and the build as they are now
    (publish.unchanged); None when there is none or anything differs. It costs the hashes of the files, one
    list and two reads: no compile, no epoch. A pack that cannot be read, or an import that is not the pinned
    one, is no reason to skip: the compiler then says what is wrong."""
    from rezono_compiler import modules

    from . import batch, view_build

    root = Path(pack_dir)
    try:
        name = yaml.safe_load((root / "pack.yaml").read_text("utf-8"))["name"]
        modules.closure(root)  # every imported pack is the one pack.yaml pins, so the pack's own hash covers them
    except (OSError, ValueError, KeyError, TypeError, AttributeError, yaml.YAMLError):
        return None  # whatever is wrong with the pack, the ordinary path reports it
    head = publish.newest_main(st, str(name))
    if head is None:
        return None
    build = batch.build_record()
    if with_views:
        build = build | {"views": view_build.component(view_build.executable())}
    if with_forms:
        build = build | {"forms": forms.component()}
    same = publish.unchanged(head, pack_sha256=batch.tree_sha256(root), engine=batch.engine_component(),
                             build=build, roles=roles)
    return head if same else None


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="rezono_publisher")
    p.add_argument("pack")
    p.add_argument("--profile", help="deploy profile with the sections storage and access")
    p.add_argument("--store", help="file:///path or s3://bucket; overrides the profile")
    p.add_argument("--role", action="append", default=[], metavar="ROLE=complete|may_read",
                   help="adds or overrides a role of the profile")
    p.add_argument("--epoch", type=int, required=True)
    p.add_argument("--knowledge-time", required=True)
    p.add_argument("--source", action="append", default=[], metavar="ID=POSITION")
    p.add_argument("--proposal", default="")
    p.add_argument("--base-manifest", default="")
    p.add_argument("--views", action="store_true", help="check and write views before publishing the manifest (main manifests only)")
    p.add_argument("--forms", action="store_true",
                   help="write each filtered role's verified Reckon Data form before the manifest (main only)")
    p.add_argument("--forms-after", action="store_true",
                   help="name the forms library in the build and write no form: they follow the publication")
    p.add_argument("--skip-unchanged", action="store_true",
                   help="publish nothing when the newest main manifest was made from the same pack and build (main manifests only)")
    args = p.parse_args(argv)

    # Where the pack may be published (SO-5): a pack whose class the profile does not carry is refused before
    # anything is computed or written. Without --profile nothing names a place (a local test with --store).
    if args.profile:
        from . import classes

        with open(args.profile, encoding="utf-8") as f:
            profile = yaml.safe_load(f) or {}
        reason = classes.refusal(args.pack, profile, Path(args.profile).name)
        if reason:
            print(f"blocked: {reason}", file=sys.stderr)
            return 2
        # A pack whose forms the profile switches off (forms.packs): its build names no forms library, so job
        # `forms` refuses it and makes nothing.
        if args.forms_after:
            try:
                args.forms_after = forms.switched_on(profile, forms.pack_name(args.pack))
            except ValueError as err:
                p.error(str(err))

    url, endpoint, roles = profile_settings(args.profile) if args.profile else (None, None, {})
    roles.update(r.split("=", 1) for r in args.role)
    url = args.store or url
    if not url:
        p.error("no store: give --store or a profile with storage")
    from . import batch  # needs the compiler with DuckDB

    try:
        st = store.open_store(url, endpoint)
        if args.skip_unchanged and not args.proposal:
            timing.switch("lookup")
            head = published(args.pack, st, roles, args.views, args.forms or args.forms_after)
            if head is not None:
                print(f"unchanged: {args.pack} is published as {head['id']}, from the same pack and build; "
                      "nothing is written", file=sys.stderr)
                print(head["id"])
                return 0
        e = batch.epoch(args.pack, epoch=args.epoch, knowledge_time=args.knowledge_time,
                        sources=[tuple(s.split("=", 1)) for s in args.source],
                        proposal=args.proposal, base_manifest=args.base_manifest)
        prepared = None
        if args.views:
            prepared = views.prepare(st, e.pack, publish.manifest_id(e),
                                     [r for r, mode in roles.items() if mode != "complete"])
            e = replace(e, build=e.build | {"views": prepared.component})
        if args.forms or args.forms_after:
            e = replace(e, build=e.build | {"forms": forms.component()})
        reuse = None
        if not e.proposal and not e.base_manifest:  # a main publication: what the newest main names is not written again
            try:
                reuse = publish.newest_main(st, e.pack)
            except ValueError as err:  # write every object: always correct, only slower
                print(f"note: no reuse, {err}", file=sys.stderr)
        m = publish.publish(e, st, roles, reuse=reuse, prepared_views=prepared, forms=args.forms)
        for role in access.without_rights(e.rows, roles):
            print(f"note: role {role} reads no element of {e.pack}: the read rules derive no may_read row for it "
                  "(a rule over every role gives only to a role the pack's facts name)", file=sys.stderr)
        print(m["id"])
    except (publish.Blocked, views.Blocked, forms.Blocked) as err:
        print(f"blocked: {err}", file=sys.stderr)
        return 2
    except (store.Conflict, ValueError, subprocess.CalledProcessError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    finally:
        # Seconds per phase, to the log and the step summary (never into the store); also when blocked.
        timing.report(args.pack)
    return 0


if __name__ == "__main__":
    sys.exit(main())
