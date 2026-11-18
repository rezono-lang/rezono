# The publish job's tools for the run on kind (README.md): the operating system the pinned Python runtime is
# built for (requirements/.python-artifact, the base of deploy/engine) and Node 24 as deploy/gate and deploy/viewer
# pin it. Nothing of Rezono is in the image: publish.sh installs the locked packages from the checkout it is given,
# as the job `publish` of .github/workflows/promote.yml does.
FROM node:26.13.1-trixie-slim@sha256:e6bedef217677b276c591795e169840edd9096dbf13f29df8ef8d1856b8820bc AS node

FROM buildpack-deps:26.10-scm@sha256:b3ce51612b50e583887ee360498db78e6e4bd3d5703131c9d165b59f8db20245
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm/ /usr/local/lib/node_modules/npm/
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && node --version && npm --version
ENTRYPOINT ["/bin/bash"]
