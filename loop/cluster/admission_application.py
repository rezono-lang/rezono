"""Render the disposable cluster's Argo CD Application for a pinned checkout."""

import argparse
import json
from pathlib import Path
import re
import tomllib
from urllib.parse import urlsplit


def load_source_profile(path: Path) -> tuple[str, str]:
    with path.open("rb") as file:
        source = tomllib.load(file)
    if set(source) != {"repository_url", "plugin_name"}:
        raise ValueError("expected repository_url and plugin_name")

    repository = source["repository_url"]
    if not isinstance(repository, str) or any(not c.isprintable() or c.isspace() for c in repository):
        raise ValueError("repository_url must be an HTTP or HTTPS URL")
    url = urlsplit(repository)
    if (url.scheme not in {"http", "https"} or not url.hostname
            or url.port == 0 or url.username is not None or url.query or url.fragment):
        raise ValueError("repository_url must be an HTTP or HTTPS URL without credentials, query or fragment")

    plugin = source["plugin_name"]
    if not isinstance(plugin, str) or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", plugin):
        raise ValueError("plugin_name must be a lowercase plugin identifier")
    return repository, plugin


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True, help="Full lowercase Git commit SHA")
    parser.add_argument("--source-profile", type=Path,
                        default=Path(__file__).with_name("admission-source.toml"),
                        help="TOML source profile (defaults to admission-source.toml beside this script)")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        parser.error("--revision requires a full lowercase Git commit SHA")
    try:
        repository, plugin = load_source_profile(args.source_profile)
    except (OSError, ValueError) as error:
        parser.error(f"invalid source profile: {error}")

    application = {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "Application",
        "metadata": {"name": "rezono-admission", "namespace": "argocd"},
        "spec": {
            "project": "default",
            "source": {
                "repoURL": repository,
                "targetRevision": args.revision,
                "path": "k8s-admission",
                "plugin": {"name": plugin},
            },
            "destination": {"server": "https://kubernetes.default.svc"},
            "syncPolicy": {"automated": {}},
        },
    }
    print(json.dumps(application, indent=2))


if __name__ == "__main__":
    main()
