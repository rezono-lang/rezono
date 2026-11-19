# The front door: readme, quickstart, container and contributing

A newcomer should see what Rezono is, try it, and know under which terms. The readme, its quickstart, a container to run the quickstart in, and a contributing guide are the front door. Each says only what is true at the commit it is read from, and a test holds each to that.

## The readme names no release that is not there

Until the first release there is no wheel, image or package to download. Until `CHANGELOG.md` has a section for a released version (a heading `## <version>`), `README.md` says "There is no release yet." and does not use the word "released". It says how to install from a checkout, which the quickstart already does.

The first release adds its section to `CHANGELOG.md`; the same pull request rewrites the readme and the test.

## The quickstart computes

The quickstart is the sequence of `bash` blocks in `README.md`, in order. `scripts/check-quickstart.sh` runs every block in order in one shell, so a later block uses the working directory and the variables of an earlier one. A block in another language, such as `sh`, is not run.

1. **`library`.** Publish the example and select the green proof check from its manifest. This is the smallest publication.
2. **`subsidy`.** Publish the example in the same working directory and end with a `jq -e` that selects one derived row and its witness. `library` has no rules, so without this step a reader sees no derived row and no witness: the first step shows that Rezono publishes, the second that it computes and proves.
3. **One assumption and its difference.** Added with the local suppose command; see [local suppose](local-suppose.md).

The check that runs the quickstart in CI is the proof with a clean copy: what the readme lets a newcomer do must succeed.

## A container for every other machine

The readme asks for Ubuntu 24.04 on x86-64 with the pinned Python. For any other machine a `Dockerfile` at the root of the repository builds an image in which the same quickstart succeeds.

- Every `FROM` names its image by digest (`@sha256:`), as other pins in the repository do.
- The readme gives the two commands that build and start the image in an `sh` block, which the quickstart check does not run.
- The image is never published. A release, and anything pushed to a registry, stays with the maintainer.
- A CI job builds the image and runs `scripts/check-quickstart.sh` in it, only when the readme, the `Dockerfile` or `requirements/` change.

## Contributing

`CONTRIBUTING.md` says only what holds now:

- report a bug with an issue and the smallest pack that shows it; report a vulnerability as `SECURITY.md` says;
- a contribution falls under the licence of the path it touches, as `NOTICE` says;
- a contributor from outside works from a fork and does not claim a task with a branch in the repository;
- checks that run code from an outside pull request start only after the maintainer approves them;
- only the maintainer sets the label `planner`.

`README.md` links it. `WORKER.md` says that its commit identity is for the project's own agents, and that anyone else uses their own name.

## Considered

- **Keep `library` as the only step.** It is the smallest proof that the toolchain works, but it shows no rule, no derived row and no witness, which is what Rezono is for.
- **Replace `library` with `subsidy`.** A failure in the larger example would then hide whether the toolchain works at all.
- **Publish the image.** It would be a release under another name; releases stay with the maintainer.
- **Build the image on every pull request.** It takes minutes and only the readme, the `Dockerfile` and the pinned requirements can break it.
