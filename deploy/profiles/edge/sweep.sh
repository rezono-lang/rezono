#!/bin/sh
# After publish.sh: the variants of each pack's sweep against its newest main manifest (docs/interaction.md,
# section 1): the one of HEAD, or an earlier one when publish.sh found the pack unchanged.
# Packs: the arguments, else publish.packs in the profile; a pack without sweeps.yaml is skipped.
# A variant that is there already is kept, so a run that stopped is completed by the next one. Exit 0: every
# variant is there. Exit 1: an error (not a red variant: that is a diagnosis, never a failure).
# Two variants are computed at a time (REZONO_SWEEP_WORKERS): a variant of the lab is 13 s of
# computation and as long again waiting on the store, so two processes halve the time one runner is held,
# for the same work. What is written does not depend on the number.
# Needs: what publish.sh needs.
set -eu
root=$(git rev-parse --show-toplevel)
profile=${REZONO_PROFILE_FILE:-$root/deploy/profiles/edge.yaml}
cd "$root"
[ "$#" -gt 0 ] || set -- $(python -c 'import sys, yaml; print(" ".join(yaml.safe_load(open(sys.argv[1]))["publish"]["packs"]))' "$profile")
worst=0
for pack in "$@"; do
  [ -f "$pack/sweeps.yaml" ] || continue
  echo "sweep $pack (against its newest main manifest)"
  status=0
  python -m rezono_publisher.sweep "$pack" --profile "$profile" --newest --workers "${REZONO_SWEEP_WORKERS:-2}" \
    ${REZONO_STORE:+--store "$REZONO_STORE"} || status=$?
  [ "$status" -le "$worst" ] || worst=$status
done
exit "$worst"
