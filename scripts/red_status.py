"""Publish the read-only policy result on the exact PR or merge-group SHA it reviewed."""
import json
import os
import re
import subprocess


def api(path):
    return json.loads(subprocess.check_output(["gh", "api", path]))


def main():
    repository = os.environ["GITHUB_REPOSITORY"]
    root = f"repos/{repository}"
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as file:
        event = json.load(file)
    run = api(f"{root}/actions/runs/{int(event['workflow_run']['id'])}")
    workflow = api(f"{root}/actions/workflows/red-policy.yml")
    if (run["workflow_id"] != workflow["id"] or run["path"] != ".github/workflows/red-policy.yml"
            or run["repository"]["full_name"] != repository
            or run["event"] not in {"pull_request_target", "merge_group"}):
        raise ValueError("unexpected policy run identity")
    match = re.fullmatch(r"policy (pull_request_target|merge_group) (\d+) ([0-9a-f]{40}) (true|false)",
                         run["display_title"])
    if not match or match[1] != run["event"]:
        raise ValueError("unexpected trusted run title")
    sha = match[3]
    if run["event"] == "pull_request_target":
        number = int(match[2])
    else:
        group = re.fullmatch(r"gh-readonly-queue/main/pr-(\d+)-[0-9a-f]+", run["head_branch"])
        if not group or run["head_sha"] != sha:
            raise ValueError("unexpected merge group identity")
        number = int(group[1])
    pr = api(f"{root}/pulls/{number}")
    if pr["state"] != "open" or pr["base"]["ref"] != "main" or pr["base"]["repo"]["full_name"] != repository:
        return
    planner = any(label["name"] == "planner" for label in pr["labels"])
    if run["event"] == "pull_request_target":
        if pr["head"]["sha"] != sha or planner != (match[4] == "true"):
            return
    state = "pending"
    if run["status"] == "completed":
        state = "success" if run["conclusion"] == "success" else "failure"
        if state == "success":
            jobs = api(f"{root}/actions/runs/{run['id']}/jobs")["jobs"]
            decisions = [step["name"] for job in jobs for step in job["steps"]
                         if step["name"] in {"Planner authorization", "Verify ordinary changes"}
                         and step["conclusion"] == "success"]
            if decisions != (["Planner authorization"] if planner else ["Verify ordinary changes"]):
                state = "failure"
    context = "red-list-policy"
    url = run["html_url"]
    statuses = api(f"{root}/commits/{sha}/status")["statuses"]
    for status in statuses:
        if status["context"] != context:
            continue
        link = status.get("target_url") or ""
        prior = re.fullmatch(re.escape(url.rsplit("/", 1)[0]) + r"/(\d+)", link)
        if prior and int(prior[1]) > run["id"]:
            return
        if link == url and status["state"] == state:
            return
    subprocess.run(["gh", "api", "--silent", "--method", "POST", f"{root}/statuses/{sha}",
                    "-f", f"state={state}", "-f", f"context={context}", "-f", f"target_url={url}",
                    "-f", f"description=Trusted test evidence review: {state}"], check=True)
    print(f"{context} {state} on {sha}")


if __name__ == "__main__":
    main()
