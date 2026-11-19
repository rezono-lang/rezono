# A machine for the README.md quickstart on any host (decisions/front-door.md): Ubuntu 24.04 on x86-64 with the
# pinned Python runtime (requirements/.python-artifact, checked against requirements/.python-digest), jq and a copy
# of this checkout. The quickstart then installs the locked packages from that copy, as on Ubuntu itself.
# The image is a local tool and is never published; README.md gives the commands that build and start it, and
# .github/workflows/quickstart-image.yml runs scripts/check-quickstart.sh in it.
FROM --platform=linux/amd64 buildpack-deps:26.10-scm@sha256:b3ce51612b50e583887ee360498db78e6e4bd3d5703131c9d165b59f8db20245

RUN apt-get -o Acquire::Retries=5 update \
 && DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=5 install -y --no-install-recommends jq \
 && rm -rf /var/lib/apt/lists/*

# The pinned runtime, installed and measured by the same script CI uses; /opt/python names its prefix.
COPY requirements/.python-artifact requirements/.python-digest /opt/rezono-runtime/requirements/
COPY scripts/python-runtime.sh scripts/python-digest.sh /opt/rezono-runtime/scripts/
RUN python=$(bash /opt/rezono-runtime/scripts/python-runtime.sh) \
 && ln -s "${python%/bin/python3}" /opt/python \
 && rm -rf /opt/rezono-runtime
ENV PATH=/opt/python/bin:$PATH \
    LD_LIBRARY_PATH=/opt/python/lib

# The checkout, owned by the image's unprivileged user (uid 1000) so its editable installs can write metadata.
WORKDIR /rezono
RUN chown 1000:1000 /rezono
COPY --chown=1000:1000 . /rezono
USER 1000:1000
CMD ["bash"]
