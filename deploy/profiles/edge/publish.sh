#!/bin/sh
# Publish one epoch of each pack (a CI job on DuckDB), from a full Git checkout of main.
# Everything comes from Git, never from the clock: the epoch is the number of commits, the knowledge
# time the commit time, the source position the commit. Packs: the arguments, else publish.packs in
# the profile. Exit 0: all published. Exit 2: a red check somewhere, nothing published for that pack.
# A pack whose newest main manifest was made from the same pack and build is not published again: that
# manifest stays the newest and nothing is computed or written (--skip-unchanged, RV-M15). REZONO_PUBLISH_ALL=1
# publishes every pack whatever the store holds.
# After each manifest, its views (rezono_publisher.views: the layout per role, made once here, never per
# request; docs/gui.md, Work per request). A view that shows more than its role reads exits 2 too.
# The publication forms (rezono_publisher.forms, RV-K16) follow the publication, in job `forms` of promote.yml: here
# a manifest only names the forms library in its build (--forms-after), so a new library publishes the pack again;
# a pack the profile's forms.packs switches off gets none (RV-K16 revised, docs/decisions.md).
# Each main manifest's head is written with it. The publish path runs no backfill of heads (RV-M10): it read
# every manifest of the pack; `python -m rezono_publisher.pointers` stays a tool an operator runs by hand.
# Needs: python with the compiler (batch) and the publisher (s3); REZONO_S3_ENDPOINT and the storage keys;
# node 24 with `npm ci` in viewer/ for the views.
set -eu
root=$(git rev-parse --show-toplevel)
profile=${REZONO_PROFILE_FILE:-$root/deploy/profiles/edge.yaml}
cd "$root"
[ "$#" -gt 0 ] || set -- $(python -c 'import sys, yaml; print(" ".join(yaml.safe_load(open(sys.argv[1]))["publish"]["packs"]))' "$profile")
commit=$(git rev-parse HEAD)
epoch=$(git rev-list --count HEAD)
time=$(git log -1 --format=%cI)
skip=--skip-unchanged
[ "${REZONO_PUBLISH_ALL:-}" != 1 ] || skip=
# RV-Z11: the run's time and every pack's phases (rezono_publisher.timing), for the budget below.
start=$(date +%s)
REZONO_TIMES_FILE=$(mktemp)
export REZONO_TIMES_FILE
worst=0
for pack in "$@"; do
  echo "publish $pack (epoch $epoch, $commit)"
  status=0
  python -m rezono_publisher "$pack" --profile "$profile" --epoch "$epoch" --knowledge-time "$time" \
    --source "rules=$commit" --views --forms-after $skip ${REZONO_STORE:+--store "$REZONO_STORE"} || status=$?
  [ "$status" -le "$worst" ] || worst=$status
done
# After the whole of publish.packs, its time against publish.budget_minutes: a warning naming the slowest pack and
# its largest phase, never a failure (deploy/profiles/edge/budget.py).
python deploy/profiles/edge/budget.py compare "$profile" $(($(date +%s) - start)) "$REZONO_TIMES_FILE" "$@" || true
rm -f "$REZONO_TIMES_FILE"
exit "$worst"
