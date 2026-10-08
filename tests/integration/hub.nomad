job "hub" {
    type = "service"

    datacenters = ["dc1"]

    group "hub" {

        network {
            mode = "host"
            port "hub" {
                to = 8000
            }
            port "api" {
                to = 8081
            }
        }
        task "hub" {
            driver = "docker"

            config {
                image = "quay.io/jupyterhub/jupyterhub:6"

                args = [
                        "jupyterhub",
                        "-f",
                        "/local/jupyterhub_config.py",
                    ]
                ports = ["hub", "api"]
                #network_mode = "host"
            }

            template {
                destination = "/local/jupyterhub_config.py"

                data = <<EOF
import json
import os
import socket
import tarfile

c.JupyterHub.bind_url = "http://0.0.0.0:8000"
c.JupyterHub.hub_bind_url = "http://0.0.0.0:8081"

c.JupyterHub.hub_connect_url = f"http://{os.environ.get('NOMAD_IP_api')}:{os.environ.get('NOMAD_HOST_PORT_api')}"
c.JupyterHub.log_level = "DEBUG"
c.ConfigurableHTTPProxy.debug = True
c.JupyterHub.authenticator_class = 'dummy'
c.JupyterHub.services = [
    {"name": "test", "api_token": "test-secret-token"},
]
# the service `admin` flag is deprecated since JupyterHub 2.0, grant the
# scopes the integration tests need via a role instead
c.JupyterHub.load_roles = [
    {
        "name": "test",
        "scopes": ["admin:users", "admin:servers"],
        "services": ["test"],
    },
]
                EOF


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
