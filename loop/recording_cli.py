"""Replay an offline recording with `python -m loop.recording_cli RECORDING`."""

import argparse
import json
import sys
from collections.abc import Sequence

from loop.recording_input import load_recording
from loop.replay import replay


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay a recorded reconciliation run.")
    parser.add_argument("recording", help="path to the recording JSON")
    args = parser.parse_args(argv)

    try:
        recording = load_recording(args.recording)
        plans, outcome = replay(**recording)
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1

    print(json.dumps({"plans": plans, "outcome": outcome, "rounds": len(plans)}))
    return 0 if outcome == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
