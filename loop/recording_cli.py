"""Replay an offline recording with `python -m loop.recording_cli RECORDING`."""

import argparse
import json
import sys
from collections.abc import Sequence

from loop.recording_input import load_recording
from loop.replay import replay, replay_report
from loop.typed_recording import TypedRecording


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay a recorded reconciliation run.")
    parser.add_argument("recording", help="path to the recording JSON")
    args = parser.parse_args(argv)

    fixed_point = []
    try:
        recording = load_recording(args.recording)
        if isinstance(recording, TypedRecording):
            plans, outcome, fixed_point = replay_report(
                recording.run, recording.limit, recording.snapshots(), report_limit=True)
        else:
            plans, outcome = replay(**recording)
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1

    report = {"plans": plans, "outcome": outcome, "rounds": len(plans)}
    if fixed_point:
        columns = ("run", "sweep", "step", "token", "requirement")
        report["fixed_point"] = [dict(zip(columns, row, strict=True)) for row in fixed_point]
    print(json.dumps(report))
    return 0 if outcome == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
