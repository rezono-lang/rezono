"""Release inactive task claims using the server activity time and an exact ref lease."""
import datetime as dt
import json
import os
import subprocess
from urllib.parse import quote


def api(endpoint, paginate=False):
    args = ["gh", "api", endpoint]
    if paginate:
        args.extend(["--paginate", "--slurp"])
        return [item for page in json.loads(subprocess.check_output(args)) for item in page]
    return json.loads(subprocess.check_output(args))


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    root = f"repos/{repo}"
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=4)
    for ref in api(f"{root}/git/matching-refs/heads/task/", paginate=True):
        branch = ref["ref"].removeprefix("refs/heads/")
        head = ref["object"]["sha"]
        activity = api(f"{root}/activity?ref={quote(ref['ref'], safe='')}&per_page=1")
        if not activity or activity[0]["after"] != head:
            continue
        last_push = dt.datetime.fromisoformat(activity[0]["timestamp"].replace("Z", "+00:00"))
        if last_push >= cutoff:
            continue
        owner = repo.split("/")[0]
        if api(f"{root}/pulls?state=open&head={quote(owner + ':' + branch)}"):
            continue
        subprocess.run(["git", "push", f"--force-with-lease={ref['ref']}:{head}",
                        "origin", f":{ref['ref']}"], check=True)
        print(f"Released {branch}")


if __name__ == "__main__":
    main()
