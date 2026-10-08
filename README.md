# Nomad Jupyter Spawner

> [!WARNING]
> This project is currently in beta

A JupyterHub plugin to spawn single-user notebook servers via [Nomad](https://www.nomadproject.io/). The project provides templates to allow users to influence how their servers are spawned (see the [showcase](#show-case) and [recipes](#recipes) for more details.).

After login users can select an image, resources and connect it with volumes (csi / host / ephemeral disk).

```sh
pip install jupyterhub-nomad-spawner
```

Requirements:

- Python 3.10+
- JupyterHub 6.x
- Nomad 1.4+ (Nomad native service discovery) with the `docker` driver

## Show Case

https://user-images.githubusercontent.com/1607547/182332760-b0f96ba2-faa8-47b6-9bd7-db93b8d31356.mp4

TODOs:

- Document setup

## Usage

### Jupyterhub Configuration

```python

import os

from jupyterhub.auth import DummyAuthenticator

c.JupyterHub.spawner_class = "nomad-spawner"
c.JupyterHub.bind_url = "http://0.0.0.0:8000"
c.JupyterHub.hub_bind_url = "http://0.0.0.0:8081"

c.JupyterHub.hub_connect_url = (
    f"http://{os.environ.get('NOMAD_IP_api')}:{os.environ.get('NOMAD_HOST_PORT_api')}"
)
c.JupyterHub.log_level = "DEBUG"
c.ConfigurableHTTPProxy.debug = True


c.JupyterHub.allow_named_servers = True
c.JupyterHub.named_server_limit_per_user = 5

c.JupyterHub.authenticator_class = DummyAuthenticator

c.NomadSpawner.datacenters = ["dc1", "dc2", "dc3"]
c.NomadSpawner.csi_plugin_ids = ["nfs", "hostpath-plugin0"]
c.NomadSpawner.mem_limit = "2G"

c.NomadSpawner.common_images = ["quay.io/jupyter/minimal-notebook:2026-10-05"]

# the Nomad namespace to create the notebook jobs in (default: "default")
c.NomadSpawner.namespace = "notebooks"

# show the full options form (volumes, memory); the default is a reduced form
# with image and datacenters only
c.NomadSpawner.lite_form = False


def csi_volume_parameters(spawner):
    if spawner.user_options["volume_csi_plugin_id"] == "nfs":
        return {"gid": "1000", "uid": "1000"}
    else:
        return None


c.NomadSpawner.csi_volume_parameters = csi_volume_parameters

```

The connection to Nomad (and Consul, if used as service provider) is configured via the usual environment variables (`NOMAD_ADDR`, `NOMAD_TOKEN`, `NOMAD_NAMESPACE`, `NOMAD_CACERT`-style `NOMAD_CA_CERT`, `NOMAD_CLIENT_CERT`, `NOMAD_CLIENT_KEY`, `NOMAD_TLS_SKIP_VERIFY`, `CONSUL_HTTP_ADDR`, ...) or the corresponding `c.NomadSpawner.*` traits (`nomad_addr`, `nomad_token`, `namespace`, ...).

### Nomad Job

```hcl

job "jupyterhub" {
    type = "service"

    datacenters = ["dc1"]

    group "jupyterhub" {

        network {
            mode = "host"
            port "hub" {
                to = 8000
                static = 8000
            }
            port "api" {
                to = 8081
            }
        }
        task "jupyterhub" {
            driver = "docker"

            config {
                image = "ghcr.io/mxab/jupyterhub-nomad-spawner:main"
                auth_soft_fail = false

                args = [
                        "jupyterhub",
                        "-f",
                        "/local/jupyterhub_config.py",
                    ]
                ports = ["hub", "api"]

            }
            template {
                destination = "/local/nomad.env"
                env = true
                data = <<EOF

NOMAD_ADDR=http://host.docker.internal:4646
CONSUL_HTTP_ADDR=http://host.docker.internal:8500
    EOF
            }
            template {
                destination = "/local/jupyterhub_config.py"

                data = <<EOF
import os

from jupyterhub.auth import DummyAuthenticator

c.JupyterHub.spawner_class = "nomad-spawner"
c.JupyterHub.bind_url = "http://0.0.0.0:8000"
c.JupyterHub.hub_bind_url = "http://0.0.0.0:8081"

c.JupyterHub.hub_connect_url = (
    f"http://{os.environ.get('NOMAD_IP_api')}:{os.environ.get('NOMAD_HOST_PORT_api')}"
)
c.JupyterHub.log_level = "DEBUG"
c.ConfigurableHTTPProxy.debug = True


c.JupyterHub.allow_named_servers = True
c.JupyterHub.named_server_limit_per_user = 5

c.JupyterHub.authenticator_class = DummyAuthenticator

c.NomadSpawner.datacenters = ["dc1", "dc2", "dc3"]
c.NomadSpawner.csi_plugin_ids = ["nfs", "hostpath-plugin0"]
c.NomadSpawner.mem_limit = "2G"

c.NomadSpawner.common_images = ["quay.io/jupyter/minimal-notebook:2026-10-05"]


def csi_volume_parameters(spawner):
    if spawner.user_options["volume_csi_plugin_id"] == "nfs":
        return {"gid": "1000", "uid": "1000"}
    else:
        return None


c.NomadSpawner.csi_volume_parameters = csi_volume_parameters

                EOF


            }

            resources {
                memory = "512"
            }

        }

        service {
            name = "jupyter-hub"
            port = "hub"

            check {
                type     = "tcp"
                interval = "10s"
                timeout  = "2s"
            }

        }
        service {
            name = "jupyter-hub-api"
            port = "api"
            check {
                type     = "tcp"
                interval = "10s"
                timeout  = "2s"
            }

        }
    }
}


```

A ready to use image with the spawner (and `oauthenticator`) installed on top of the official `jupyterhub/jupyterhub` image is built from the [Dockerfile](Dockerfile) in this repository.

## Recipes

By default the `jupyterhub-nomad-spawner` allows users to customize the notebook servers image, the datacenters to spawn in, as well as the memory and volume type for the allocation. While these options are sufficient in most cases, `jupyterhub` operators may wish to customize the spawner's behavior and/or restrict the notebook users customization.

- using a custom job spec

  ```python
  # must be available to your hub server
  c.NomadSpawner.job_template_path = "/etc/jupyterhub/custom-job-template.hcl.j2"

  ```

- disabling user options

  ```python
  # skips the options dialogue, which is used to populate `NomadSpawner.user_options`
  # therefore you would also have to overwrite the default `job_factory``
  c.NomadSpawner.options_form = ""
  ```

- using a custom job factory

  ```python
  from jupyterhub_nomad_spawner.spawner import NomadSpawner
  from jupyterhub_nomad_spawner.job_factory import (
    JobData,
    create_job,
    )


  class CustomNomadSpawner(NomadSpawner):
    async def job_factory(self, _) -> str:
        return create_job(
            job_data=JobData(
                job_name=self.job_name,
                username=self.user.name,
                notebook_name=self.name,
                service_provider=self.service_provider,
                service_name=self.service_name,
                env=self.get_env(),
                args=self.get_args(),
                image="quay.io/jupyter/minimal-notebook",
                datacenters=["dc1", "dc2"],
                cpu=500,
                memory=512,
                namespace=self.namespace,
            ),
            job_template_path=self.job_template_path,
        )

    c.JupyterHub.spawner_class = CustomNomadSpawner
  ```

- customizing server naming

  ```python
  c.NomadSpawner.base_job_name = "jupyter"   # used as prefix
  c.NomadSpawner.name_template = "{{prefix}}-{{username}}"
  ```

> [!NOTE]
> Please be aware that if you have enabled named servers, the template should contain the {{notebookid}}.

## Development

### Setup

Requires Python 3.10+ and [Poetry](https://python-poetry.org/docs/#installation) 2.x.

```sh
poetry install --with dev
poetry run pytest

# formatting, type checking and linting
poetry run poe check
```

The unit tests compare rendered jobs and forms against the fixtures in `tests/fixtures`. After an intentional template change regenerate them with:

```sh
poetry run pytest --update-job-fixtures --update-job-options-fixtures
```

The integration tests need a local `nomad` and `consul` binary as well as Docker and are only run with `poetry run pytest --runintegration`.

The pydantic models of the Nomad API in `jupyterhub_nomad_spawner/nomad/nomad_model.py` are generated from the (archived, but still accurate for the endpoints in use) [Nomad OpenAPI spec](https://github.com/hashicorp/nomad-openapi):

```sh
poetry run poe gen-nomad-model
```

### Release

Bump `version` in `pyproject.toml` and push a `v*.*.*` tag; the release workflow builds and publishes the package to PyPI. Images for every push to `main` are published to the GitHub container registry by the Docker workflow.
