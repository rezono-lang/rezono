"""Print grouped changes since the last release, or validate a squash subject."""
import argparse
import subprocess

TOPICS = {
    "Features": "Add Build Create Enable Implement Introduce Model Provide Support",
    "Corrections": "Correct Fail Fix Guard Handle Prevent Reject Remove Repair Restore Verify",
    "Changes": "Adopt Allow Change Check Configure Convert Define Enforce Extend Extract Generate Improve Include Make Move Package Parallelize Prepare Preserve Refactor Rename Replace Require Run Set Simplify Specify Split Switch Update Use Validate",
    "Documentation and tests": "Clarify Cover Describe Document Exercise Explain Record Review Test",
}


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def topic(subject):
    verb = (subject.split() or [""])[0]
    return next((key for key, words in TOPICS.items() if verb in words.split()), None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject")
    parser.add_argument("--topics", action="store_true")
    args = parser.parse_args()
    if args.topics:
        for label, words in TOPICS.items():
            print(f"{label}: {words}")
    elif args.subject is not None:
        if not topic(args.subject):
            parser.error("Start the pull request title with a topic verb from --topics.")
    else:
        tags = git("tag", "--merged", "HEAD", "--list", "v[0-9]*", "--sort=-version:refname").splitlines()
        base = tags[0] if tags else "326eb3cbcd8fe8dbf07b6750659d48fc5f179bca"
        subjects = git("log", "--first-parent", "--no-merges", "--format=%s", f"{base}..HEAD").splitlines()
        for section in [*TOPICS, "Other changes"]:
            items = [s for s in subjects if (topic(s) or "Other changes") == section]
            if items:
                print(f"## {section}\n")
                print("\n".join(f"- {s}" for s in items), end="\n\n")


if __name__ == "__main__":
    main()
