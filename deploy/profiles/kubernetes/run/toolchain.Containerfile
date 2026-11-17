# The publish job's tools for the run on kind (README.md): the operating system the pinned Python runtime is
# built for (requirements/.python-artifact, the base of deploy/engine) and Node 24 as deploy/gate and deploy/viewer
# pin it. Nothing of Rezono is in the image: publish.sh installs the locked packages from the checkout it is given,
# as the job `publish` of .github/workflows/promote.yml does.
FROM node:24.22.3-trixie-slim@sha256:af02d57b57719b9657a45199a79264a9437940cd55b3c7b3fc99615654f124a0 AS node

FROM buildpack-deps:24.04-scm@sha256:94ed690dd634b8b2f531eaa742fde9b1264077cd8ea695a3b960bd104ae4c481
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm/ /usr/local/lib/node_modules/npm/
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && node --version && npm --version
ENTRYPOINT ["/bin/bash"]
