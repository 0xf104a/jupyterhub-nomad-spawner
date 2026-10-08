# syntax=docker/dockerfile:1
ARG JUPYTERHUB_VERSION=6.0.1

FROM quay.io/jupyterhub/jupyterhub:${JUPYTERHUB_VERSION} AS builder

WORKDIR /opt/jupyterhub-nomad-spawner

RUN --mount=type=cache,target=/root/.cache/pip \
    python3 -m pip install --upgrade pip build

COPY pyproject.toml README.md LICENSE ./
COPY jupyterhub_nomad_spawner ./jupyterhub_nomad_spawner

# pure python wheel; the build backend (poetry-core) is fetched by `build`
RUN --mount=type=cache,target=/root/.cache/pip \
    python3 -m build --wheel --outdir dist


FROM quay.io/jupyterhub/jupyterhub:${JUPYTERHUB_VERSION} AS jupyterhub

RUN apt-get update \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*

RUN --mount=type=cache,target=/root/.cache/pip \
    python3 -m pip install --upgrade pip

RUN --mount=type=bind,from=builder,source=/opt/jupyterhub-nomad-spawner/dist,target=/tmp/dist \
    --mount=type=cache,target=/root/.cache/pip \
    python3 -m pip install oauthenticator /tmp/dist/*.whl
