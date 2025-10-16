# syntax=docker/dockerfile:1.4
FROM jupyterhub/jupyterhub:5.4.0 as builder

RUN apt update && apt upgrade -y && apt install -y git python3-venv python3-dev build-essential autoconf libtool pkg-config libffi-dev python3-cffi
RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH "/root/.local/bin/:$PATH"
RUN poetry config virtualenvs.create false

RUN mkdir -p /opt/jupyterhub-nomad-spawner/jupyterhub_nomad_spawner

COPY poetry.lock pyproject.toml /opt/jupyterhub-nomad-spawner/
RUN touch /opt/jupyterhub-nomad-spawner/jupyterhub_nomad_spawner/__init__.py /opt/jupyterhub-nomad-spawner/README.md


WORKDIR /opt/jupyterhub-nomad-spawner
RUN poetry lock
RUN --mount=type=cache,target=/root/.cache/pypoetry --mount=type=cache,target=/root/.cache/pip poetry install --only main -n -vv
COPY jupyterhub_nomad_spawner /opt/jupyterhub-nomad-spawner/jupyterhub_nomad_spawner
COPY README.md  /opt/jupyterhub-nomad-spawner/

RUN poetry build -f wheel


FROM jupyterhub/jupyterhub:5.4.0 AS jupyterhub
RUN apt update && apt upgrade -y && apt install -y python3-cffi
RUN --mount=type=cache,target=/root/.cache/pip python3 -m pip install --upgrade pip
RUN --mount=type=cache,target=/root/.cache/pip python3 -m pip -v install oauthenticator

RUN --mount=type=bind,target=/opt/jupyterhub-nomad-spawner/dist/,source=/opt/jupyterhub-nomad-spawner/dist/,from=builder --mount=type=cache,target=/root/.cache/pip python3 -m pip -v install /opt/jupyterhub-nomad-spawner/dist/*.whl
