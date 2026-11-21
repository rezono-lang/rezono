"""Report elapsed waiting and completion only from current step evidence."""

from status_times import times


def test_status_times():
    scope = {"run": "r", "tenant": "elm", "delivery": "elm-1", "step": "database"}
    def event(state, minute, **overrides):
        return {**scope, "state": state, "at": f"2030-01-01T10:{minute:02}:00Z", **overrides}
    wait = event("waiting", 4)
    watermark = event("sweep", 7)
    done = event("done", 9)
    assert times(scope, [watermark, wait, event("done", 6, run="old")]) == (180, None)
    assert times(scope, [done, wait, watermark]) == (300, done["at"])
    assert times(scope, []) == (None, None)
