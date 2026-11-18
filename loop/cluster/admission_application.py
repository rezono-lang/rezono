"""Render the disposable cluster's Argo CD Application for a pinned checkout."""

import argparse
import json
import re


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True, help="Full lowercase Git commit SHA")
    revision = parser.parse_args().revision
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        parser.error("--revision requires a full lowercase Git commit SHA")

    application = {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "Application",
        "metadata": {"name": "rezono-admission", "namespace": "argocd"},
        "spec": {
            "project": "default",
            "source": {
                "repoURL": "http://fixture-git.fixture-system.svc/rezono.git",
                "targetRevision": revision,
                "path": "k8s-admission",
                "plugin": {"name": "rezono-admission-fixture"},
            },
            "destination": {"server": "https://kubernetes.default.svc"},
            "syncPolicy": {"automated": {}},
        },
    }
    print(json.dumps(application, indent=2))


if __name__ == "__main__":
    main()
