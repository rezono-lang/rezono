"""Check the keys of a CI job before it does anything, and fail loudly if one is missing, expired or
revoked: a job without working keys must never pass quietly (profile edge).

  python deploy/profiles/edge/preflight.py s3    the R2 keys of environment publish: can they see the bucket?
  python deploy/profiles/edge/preflight.py git   the Git token of environment propose: may it read the repository?

The names of the variables and the bucket come from deploy/profiles/edge.yaml. Exit 1 with an ::error::.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

PROFILE = Path(__file__).resolve().parent.parent / "edge.yaml"
RENEW = "renew it (the GitHub tokens of the pilot expire on 06-12-2026) and update the secret in the environment"


def fail(message: str) -> None:
    print(f"::error::{message}")
    sys.exit(1)


def need(*names: str) -> None:
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        fail(f"missing secrets: {', '.join(missing)}; set them in the environment of this job")


def s3(cfg: dict) -> None:
    storage = cfg["storage"]
    need(storage["endpoint_env"], "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError, EndpointConnectionError

    client = boto3.client("s3", endpoint_url=os.environ[storage["endpoint_env"]], region_name="auto",
                          config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 2}))
    try:
        client.head_bucket(Bucket=storage["bucket"])
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "?")
        fail(f"the storage refused the keys for bucket {storage['bucket']!r} ({code}): expired, revoked or "
             f"without rights on the bucket? Make new keys and update the secrets")
    except EndpointConnectionError:
        fail(f"the storage endpoint in {storage['endpoint_env']} cannot be reached")


def git(cfg: dict) -> None:
    g = cfg["git"]
    need(g["token_env"])
    api = g.get("api") or ("https://api.github.com" if g["host"] == "github" else f"{g['url'].rstrip('/')}/api/v1")
    auth = f"Bearer {os.environ[g['token_env']]}" if g["host"] == "github" else f"token {os.environ[g['token_env']]}"
    req = urllib.request.Request(f"{api}/repos/{g['repository']}", headers={"authorization": auth,
                                                                         "accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            perms = json.load(r).get("permissions") or {}
    except urllib.error.HTTPError as e:
        fail(f"the Git host refused {g['token_env']} ({e.code}): expired or revoked? {RENEW}")
    except urllib.error.URLError as e:
        fail(f"the Git host cannot be reached: {e.reason}")
    if perms and not perms.get("push"):
        fail(f"{g['token_env']} may not push to {g['repository']}; it needs contents and pull requests: write")


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    checks = {"s3": s3, "git": git}
    if len(args) != 1 or args[0] not in checks:
        print(__doc__, file=sys.stderr)
        return 2
    checks[args[0]](yaml.safe_load(PROFILE.read_text("utf-8")))
    print(f"preflight {args[0]}: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
