# A machine for the README.md quickstart on any host (decisions/front-door.md): Ubuntu 24.04 on x86-64 with the
# pinned Python runtime (requirements/.python-artifact, checked against requirements/.python-digest), Node 24 for
# the reader of authored .rezono pack sources, jq and a copy of this checkout. The quickstart then installs the
# locked packages from that copy, as on Ubuntu itself.
# The image is a local tool and is never published; README.md gives the commands that build and start it, and
# .github/workflows/quickstart-image.yml runs scripts/check-quickstart.sh in it.
# Node 24 comes from the same pinned image as deploy/profiles/kubernetes/run/toolchain.Containerfile.
FROM --platform=linux/amd64 node:24.22.3-trixie-slim@sha256:af02d57b57719b9657a45199a79264a9437940cd55b3c7b3fc99615654f124a0 AS node

FROM --platform=linux/amd64 buildpack-deps:24.04-scm@sha256:94ed690dd634b8b2f531eaa742fde9b1264077cd8ea695a3b960bd104ae4c481

RUN apt-get -o Acquire::Retries=5 update \
 && DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=5 install -y --no-install-recommends jq \
 && rm -rf /var/lib/apt/lists/*

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm/ /usr/local/lib/node_modules/npm/
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && node --version && npm --version

# The pinned runtime, installed and measured by the same script CI uses; /opt/python names its prefix.
COPY requirements/.python-artifact requirements/.python-digest /opt/rezono-runtime/requirements/
COPY scripts/python-runtime.sh scripts/python-digest.sh /opt/rezono-runtime/scripts/
RUN python=$(bash /opt/rezono-runtime/scripts/python-runtime.sh) \
 && ln -s "${python%/bin/python3}" /opt/python \
 && rm -rf /opt/rezono-runtime
ENV PATH=/opt/python/bin:$PATH \
    LD_LIBRARY_PATH=/opt/python/lib

# The checkout, owned by the image's unprivileged user (uid 1000) so its editable installs can write metadata.
# The compiler of an editable install reads .rezono sources with rezono/, so its locked packages come along.
WORKDIR /rezono
RUN chown 1000:1000 /rezono
COPY --chown=1000:1000 . /rezono
USER 1000:1000
RUN npm ci --prefix rezono --cache /tmp/npm-cache --no-audit --no-fund \
 && rm -rf /tmp/npm-cache
CMD ["bash"]
