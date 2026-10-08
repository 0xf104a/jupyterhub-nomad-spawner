import asyncio
import hashlib
import os
import re
import ssl
import typing as t
from pathlib import Path
from textwrap import dedent
from typing import Dict, List, Optional, Tuple, TypeVar, Union

from httpx import AsyncClient
from jupyterhub.spawner import Spawner
from pydantic import AnyHttpUrl
from tenacity import retry, stop_after_attempt, wait_fixed
from traitlets import Bool
from traitlets import Callable as TCallable
from traitlets import Dict as TDict
from traitlets import Enum as TEnum
from traitlets import Int as TInt
from traitlets import List as TList
from traitlets import Unicode
from traitlets import Union as TUnion
from traitlets import default

from jupyterhub_nomad_spawner.consul.consul_service import (
    ConsulService,
    ConsulServiceConfig,
    ConsulTLSConfig,
)
from jupyterhub_nomad_spawner.job_factory import (
    JobData,
    JobVolumeData,
    ServiceProvider,
    VolumeType,
    create_job,
    create_job_name,
)
from jupyterhub_nomad_spawner.job_options_factory import create_form
from jupyterhub_nomad_spawner.nomad.nomad_service import (
    NomadService,
    NomadServiceConfig,
    NomadTLSConfig,
)

RFC_1123_2_1_NAME_PATTERN = re.compile(r"^[a-z0-9\-]+$")
T = TypeVar("T")


class NomadSpawner(Spawner):
    # Set by `start` (and restored by `load_state`); identifies the job / volume
    # of this spawner instance.
    notebook_id: Optional[str] = None

    # Nomad
    nomad_addr = Unicode(help="""
        The nomad address to use.
        """).tag(config=True)

    @default("nomad_addr")
    def _default_nomad_addr(self):
        self.log.warning("nomad_addr not set, using default")
        return os.environ.get("NOMAD_ADDR", "http://localhost:4646")

    nomad_token = Unicode(help="""
        The nomad token
        """).tag(config=True)

    @default("nomad_token")
    def _nomad_token_default(self):
        return os.environ.get("NOMAD_TOKEN", "")

    nomad_ca_cert = Unicode(help="""
        Path to a PEM encoded CA cert file to use to verify the Nomad server
        SSL certificate.
        """).tag(config=True)

    @default("nomad_ca_cert")
    def _nomad_ca_cert_default(self):
        return os.environ.get("NOMAD_CA_CERT", "")

    nomad_ca_path = Unicode(help="""
        Path to a directory of PEM encoded CA cert files to verify the Nomad
        server SSL certificate.
        """).tag(config=True)

    @default("nomad_ca_path")
    def _nomad_ca_path_default(self):
        return os.environ.get("NOMAD_CA_PATH", "")

    nomad_client_cert = Unicode(help="""
        Path to a PEM encoded client certificate for TLS authentication to the
        Nomad server.
        """).tag(config=True)

    @default("nomad_client_cert")
    def _nomad_client_cert_default(self):
        return os.environ.get("NOMAD_CLIENT_CERT", "")

    nomad_client_key = Unicode(help="""
        Path to an unencrypted PEM encoded private key matching the client
        certificate.
        """).tag(config=True)

    @default("nomad_client_key")
    def _nomad_client_key_default(self):
        return os.environ.get("NOMAD_CLIENT_KEY", "")

    nomad_tls_server_name = Unicode(help="""
        The server name to use as the SNI host when connecting via TLS.
        """).tag(config=True)

    @default("nomad_tls_server_name")
    def _nomad_tls_server_name_default(self):
        return os.environ.get("NOMAD_TLS_SERVER_NAME", "")

    nomad_tls_skip_verify = Bool(help="""
        Do not verify TLS certificates. This is strongly discouraged.
        """).tag(config=True)

    @default("nomad_tls_skip_verify")
    def _nomad_tls_skip_verify_default(self):
        verify = os.environ.get("NOMAD_TLS_SKIP_VERIFY", "")
        return verify.lower() in ("yes", "true", "t", "1")

    # Consul
    consul_http_addr = Unicode(help="""
        The consul address to use.
        """).tag(config=True)

    @default("consul_http_addr")
    def _default_consul_http_addr(self):
        return os.environ.get("CONSUL_HTTP_ADDR", "http://localhost:8500")

    consul_http_token = Unicode(help="""
        The consul token
        """).tag(config=True)

    @default("consul_http_token")
    def _consul_http_token_default(self):
        return os.environ.get("CONSUL_HTTP_TOKEN", "")

    consul_ca_cert = Unicode(help="""
        Path to a PEM encoded CA cert file to use to verify the Consul server
        SSL certificate.
        """).tag(config=True)

    @default("consul_ca_cert")
    def _consul_ca_cert_default(self):
        return os.environ.get("CONSUL_CA_CERT", "")

    consul_ca_path = Unicode(help="""
        Path to a directory of PEM encoded CA cert files to verify the Consul
        server SSL certificate.
        """).tag(config=True)

    @default("consul_ca_path")
    def _consul_ca_path_default(self):
        return os.environ.get("CONSUL_CA_PATH", "")

    consul_client_cert = Unicode(help="""
        Path to a PEM encoded client certificate for TLS authentication to the
        Consul server.
        """).tag(config=True)

    @default("consul_client_cert")
    def _consul_client_cert_default(self):
        return os.environ.get("CONSUL_CLIENT_CERT", "")

    consul_client_key = Unicode(help="""
        Path to an unencrypted PEM encoded private key matching the client
        certificate.
        """).tag(config=True)

    @default("consul_client_key")
    def _consul_client_key_default(self):
        return os.environ.get("CONSUL_CLIENT_KEY", "")

    consul_tls_server_name = Unicode(help="""
        The server name to use as the SNI host when connecting via TLS.
        """).tag(config=True)

    @default("consul_tls_server_name")
    def _consul_tls_server_name_default(self):
        return os.environ.get("CONSUL_TLS_SERVER_NAME", "")

    consul_tls_skip_verify = Bool(help="""
        Do not verify TLS certificates. This is strongly discouraged.
        """).tag(config=True)

    @default("consul_tls_skip_verify")
    def _consul_tls_skip_verify_default(self):
        verify = os.environ.get("CONSUL_TLS_SKIP_VERIFY", "")
        return verify.lower() in ("yes", "true", "t", "1")

    @default("ip")
    def _default_ip(self):
        return "0.0.0.0"

    @default("port")
    def _default_port(self):
        return 8888

    @default("env_keep")
    def _default_env_keep(self):
        return [
            "CONDA_ROOT",
            "CONDA_DEFAULT_ENV",
            "VIRTUAL_ENV",
            "LANG",
            "LC_ALL",
            "JUPYTERHUB_SINGLEUSER_APP",
        ]

    common_images = TList(
        Unicode(),
        help="""
        A list of images that are pre selectable
        """,
    ).tag(config=True)

    @default("common_images")
    def _default_common_images(self) -> t.List[str]:
        return [
            "quay.io/jupyter/base-notebook:latest",
            "quay.io/jupyter/minimal-notebook:latest",
            "quay.io/jupyter/scipy-notebook:latest",
        ]

    datacenters = TList(
        Unicode(),
        help="""
        The list of available datacenters
        """,
    ).tag(config=True)

    csi_plugin_ids = TList(
        Unicode(),
        help="""
        A list of CSI Plugins.

        """,
    ).tag(config=True)

    @default("csi_plugin_ids")
    def _default_csi_plugin_ids(self) -> t.List[str]:
        return []

    base_job_name = Unicode(help="""
        The base name of the job. Used as prefix with the name_template
        """).tag(config=True)

    @default("base_job_name")
    def _default_base_job_name(self):
        return "jupyterhub-notebook"

    auto_remove_jobs = Bool(help="""
        Specifies whether the job should be stopped and removed immediately
        (`auto_remove_jobs=True`) or deferred to the Nomad garbage collector
        (`auto_remove_jobs=False`).
        Defaults to False.
        """).tag(config=True)

    @default("auto_remove_jobs")
    def _default_auto_remove_jobs(self):
        return False

    @property
    def job_name(self) -> str:
        if self.notebook_id:
            return self._render_name_template()
        raise ValueError("notebook_id is not set")

    base_csi_volume_name = Unicode(help="""
        The base name of the csi volume. Will be concated with -<notebook_id>
    """).tag(config=True)

    @default("base_csi_volume_name")
    def _default_base_csi_volume_name(self):
        return "jupyterhub-notebook"

    csi_volume_parameters = TUnion(
        [TCallable(), TDict()],
        help="""
        When a CSI Volume is used, calculate the extra parameters
        def csi_volume_parameters(spawner):
            if spawner.user_options["volume_csi_plugin_id"] == "rocketduck-csi-plugin":
                return {
                    "gid" : 1000,
                    "uid" : 1000,
                    "mode" : "770"
                }
            else:
                return None
        c.NomadSpawner.csi_volume_parameters = csi_volume_parameters
        """,
    ).tag(config=True)

    vault_policies = TUnion(
        [TCallable(), TList()],
        help="""
        When a list of vault policies or a callable that returns a list
        def vault_policies(spawner):
            return [
                "my-vault-policy", f"user-policy-{spawner.user.name}"
            ]
        c.NomadSpawner.vault_policies = vault_policies
        """,
    ).tag(config=True)

    csi_capacity = TInt(
        help="""
        The min csi capacity in bytes
        e.g.

        c.NomadSpawner.csi_capacity = 13421772
        """,
    ).tag(config=True)

    ephemeral_disk_size = TInt(
        help="""
        The ephemeral disk size in MB
        e.g.

        c.NomadSpawner.ephemeral_disk_size = 4096
        """,
        default_value=1024,
    ).tag(config=True)

    service_provider = TEnum(
        values=["nomad", "consul"],
        default_value="nomad",
        help="""
        The service provider to use
        """,
    ).tag(config=True)

    namespace = Unicode(help="""
        The Nomad namespace the notebook jobs (and their CSI volumes) are
        created in. Defaults to the `NOMAD_NAMESPACE` environment variable or
        "default".
        """).tag(config=True)

    @default("namespace")
    def _default_namespace(self):
        return os.environ.get("NOMAD_NAMESPACE", "default")

    lite_form = Bool(help="""
        Show a minimal options form (image and datacenters only) instead of the
        full one.
        """).tag(config=True)

    @default("lite_form")
    def _default_lite_form(self):
        return True

    @property
    def csi_volume_name(self) -> str:
        if self.notebook_id:
            return f"{self.base_csi_volume_name}-{self.notebook_id}"
        raise ValueError("notebook_id is not set")

    @property
    def service_name(self) -> str:
        if self.notebook_id:
            return f"{self.job_name}"
        raise ValueError("notebook_id is not set")

    job_template_path = Unicode(help="""
        The path to the job template file with jinja2 placeholders
        see templates/job.hcl.j2
    """).tag(config=True)

    name_template = Unicode(
        config=True,
        help=dedent("""
            Name of the container or service: with {{prefix}}, {{username}},
            {{servername}} and {{notebookid}} replacements.
            It is important to include {{servername}} if JupyterHub's "named
            servers" are enabled (``JupyterHub.allow_named_servers = True``).
            The default name_template is "{{prefix}}-{{notebookid}}".
            """),
    )

    @default("name_template")
    def _default_name_template(self):
        return "{{prefix}}-{{notebookid}}"

    def _render_name_template(self):
        data = {
            "prefix": self.base_job_name,
            "username": self.user.name,
            "servername": self.name,
            "notebookid": self.notebook_id,
        }
        job_name = create_job_name(self.name_template, data=data)

        job_name_default = create_job_name(self._default_name_template(), data=data)

        if len(job_name) >= 64:
            # character limit of nomad
            message = (
                "Job name exceeds character limit of 63 characters. "
                f"Fallback to default template for {job_name=} with {job_name_default=}"
            )
        elif not re.match(pattern=RFC_1123_2_1_NAME_PATTERN, string=job_name):
            # does not match required pattern
            message = (
                r"Job name does not match required pattern ^[a-z0-9\-]+$. "
                f"Fallback to default template for {job_name=} with {job_name_default=}"
            )
        else:
            # name matches requirements
            return job_name

        self.log.warning(message)

        return job_name_default

    @staticmethod
    def clear_params(param: Union[T, List[T]]) -> T:
        if isinstance(param, list):
            return param[0]
        return param

    async def job_factory(self, nomad_service) -> str:
        """Factory for the nomad jobs to spawn.

        To customize this factory overwrite this method with your own logic.
        """
        volume_data: Optional[JobVolumeData] = None

        if self.user_options.get("volume_type", None):
            volume_data = await self.create_job_volume_data(nomad_service)

        policies: List[str] = []
        if callable(self.vault_policies):
            policies = self.vault_policies(self)
        elif self.vault_policies:
            policies = self.vault_policies

        job_hcl = create_job(
            job_data=JobData(
                job_name=self.job_name,
                username=self.user.name,
                notebook_name=self.name,
                service_provider=ServiceProvider(self.service_provider),
                service_name=self.service_name,
                env=self.get_env(),
                args=self.get_args(),
                image=self.clear_params(self.user_options["image"]),
                datacenters=self.user_options["datacenters"],
                memory=int(self.clear_params(self.user_options["memory"])),
                volume_data=volume_data,
                policies=policies,
                namespace=self.namespace,
            ),
            job_template_path=self.job_template_path,
        )

        return job_hcl

    async def start(self):
        nomad_service_config = build_nomad_config_from_options(self)
        nomad_httpx_client = build_nomad_httpx_client(nomad_service_config)
        nomad_service = NomadService(
            client=nomad_httpx_client, log=self.log, namespace=self.namespace
        )

        try:
            notebook_id: str = hashlib.sha1(
                f"{self.user.name}:{self.name}".encode("utf-8")
            ).hexdigest()[:10]
            self.notebook_id = notebook_id

            self.log.info("server name: %s", self.name)

            job_hcl = await self.job_factory(nomad_service)

            self.log.info("scheduling job %s", self.job_name)
            await nomad_service.schedule_job(job_hcl)
            await self._ensure_running(nomad_service=nomad_service)

            ip, port = await self.fetch_from_service_provider(nomad_service)
        except Exception:
            self.log.exception("Failed to start")
            raise

        finally:
            await nomad_httpx_client.aclose()

        if ":" in ip:
            # ipv6 needs [::] in url
            ip = f"[{ip}]"
        return f"http://{ip}:{port}"

    async def fetch_from_service_provider(self, nomad_service) -> Tuple[str, int]:
        """Helper to fetch spawned server's IP and port from the service provider
        (nomad/consul).

        This method is called from `start`, after the server is running.
        If your setup differs, you may wish to overwrite it with some custom logic.
        """
        if self.service_provider == "nomad":
            return await self.address_and_port_from_nomad(nomad_service)

        elif self.service_provider == "consul":
            consul_service_config = build_consul_config_from_options(self)
            async with build_consul_httpx_client(
                consul_service_config
            ) as consul_httpx_client:
                consul_service = ConsulService(client=consul_httpx_client, log=self.log)

                return await self.address_and_port_from_consul(consul_service)
        else:
            raise ValueError("Unknown service provider")

    async def create_job_volume_data(self, nomad_service: NomadService):
        volume_type = self.user_options["volume_type"]
        self.log.info("Configuring volume of type: %s", volume_type)
        volume_data: Optional[JobVolumeData] = None

        if volume_type == "csi":
            volume_id = self.csi_volume_name
            parameters = self._get_csi_extra_parameters()

            min_size: Optional[int] = self.csi_capacity
            await nomad_service.create_volume(
                id=volume_id,
                plugin_id=self.user_options["volume_csi_plugin_id"],
                parameters=parameters,
                min_size=min_size,
            )
            volume_data = JobVolumeData(
                type=VolumeType.csi,
                destination=self.user_options["volume_destination"],
                source=volume_id,
            )
        elif volume_type == "host":
            volume_data = JobVolumeData(
                type=VolumeType.host,
                destination=self.user_options["volume_destination"],
                source=self.user_options["volume_source"],
            )
        elif volume_type == "ephemeral_disk":
            volume_data = JobVolumeData(
                type=VolumeType.ephemeral_disk,
                destination=self.user_options["volume_destination"],
                ephemeral_disk_size=self.ephemeral_disk_size,
            )

        return volume_data

    def _get_csi_extra_parameters(self) -> Optional[Dict]:
        parameters: Optional[Dict] = None
        if callable(self.csi_volume_parameters):
            parameters = self.csi_volume_parameters(self)
        else:
            parameters = self.csi_volume_parameters
        return parameters

    async def _ensure_running(self, nomad_service: NomadService):
        while True:
            try:
                job_status = await nomad_service.job_status(self.job_name)
                if job_status == "dead":
                    raise Exception(f"Job (name={self.job_name}) is dead")
                elif job_status == "running":
                    task_status = await nomad_service.task_status(self.job_name)
                    if task_status == "running":
                        break
                    elif task_status == "dead":
                        raise Exception(f"Task for job (name={self.job_name}) is dead")
                    else:
                        self.log.info(
                            "Task for %s is %s, waiting...", self.job_name, task_status
                        )
                else:
                    self.log.info("Job %s is %s, waiting...", self.job_name, job_status)
            except Exception:
                self.log.exception("Failed to get job/task status")
                raise

            await asyncio.sleep(5)

    @retry(wait=wait_fixed(3), stop=stop_after_attempt(5))
    async def address_and_port_from_consul(
        self, consul_service: ConsulService
    ) -> Tuple[str, int]:
        self.log.info("Getting service %s from consul", self.service_name)
        nodes = await consul_service.health_service(self.service_name)

        address = nodes[0]["Service"]["Address"]
        port = nodes[0]["Service"]["Port"]

        return (address, port)

    @retry(wait=wait_fixed(3), stop=stop_after_attempt(5))
    async def address_and_port_from_nomad(
        self, nomad_service: NomadService
    ) -> Tuple[str, int]:
        self.log.info("Getting service %s from nomad", self.service_name)
        return await nomad_service.get_service_address(self.service_name)

    @retry(wait=wait_fixed(3), stop=stop_after_attempt(5))
    async def address_and_port_of_consul_service_from_nomad(
        self, nomad_service: NomadService
    ) -> Tuple[str, int]:
        self.log.info("Getting allocation id of %s from nomad", self.service_name)
        allocations = await nomad_service.job_allocations(self.job_name)

        # there should only be one allocation
        return await nomad_service.get_service_of_allocation(
            allocation_id=allocations[0]["ID"]
        )

    async def poll(self):
        if not self.notebook_id:
            # never started (or state was cleared): behave as "not running"
            return 0

        nomad_httpx_client = build_nomad_httpx_client(
            build_nomad_config_from_options(self)
        )
        nomad_service = NomadService(
            client=nomad_httpx_client, log=self.log, namespace=self.namespace
        )
        try:
            status = await nomad_service.job_status(self.job_name)
        except Exception:
            self.log.exception("Failed to poll")
            return -1
        finally:
            await nomad_httpx_client.aclose()

        if status == "running":
            return None

        self.log.warning("jupyter notebook not running (%s): %s", self.job_name, status)
        return 0

    async def stop(self, now=False):
        nomad_service_config = build_nomad_config_from_options(self)
        nomad_httpx_client = build_nomad_httpx_client(nomad_service_config)
        nomad_service = NomadService(
            client=nomad_httpx_client, log=self.log, namespace=self.namespace
        )

        try:
            await nomad_service.delete_job(self.job_name, purge=self.auto_remove_jobs)
            self.clear_state()
        except Exception:
            self.log.exception("Failed to stop")
        finally:
            await nomad_httpx_client.aclose()

    def get_state(self):
        """get the current state"""
        state = super().get_state()
        state["notebook_id"] = self.notebook_id

        return state

    def load_state(self, state):
        """load state from the database"""
        super().load_state(state)
        if "notebook_id" in state:
            self.notebook_id = state["notebook_id"]

    def clear_state(self):
        """clear any state (called after shutdown)"""
        super().clear_state()
        self.notebook_id = None

    @default("options_form")
    def _default_options_form(self):
        return create_form(
            datacenters=self.datacenters,
            common_images=self.common_images,
            memory_limit=self.memory_limit_in_mb,
            csi_plugin_ids=self.csi_plugin_ids,
            lite_form=self.lite_form,
        )

    @property
    def memory_limit_in_mb(self) -> Optional[int]:
        return int(self.mem_limit // (1024 * 1024)) if self.mem_limit else None

    @default("options_from_form")
    def _options_from_form_default(self):
        # JupyterHub >= 5 no longer calls `_default_options_from_form`, the
        # parsing has to be registered as the trait's default explicitly.
        return self._default_options_from_form

    def _default_options_from_form(self, form_data):
        options = {}
        options["image"] = form_data["image"][0]
        options["datacenters"] = form_data["datacenters"]
        options["memory"] = int(form_data["memory"][0])
        options["volume_type"] = form_data.get("volume_type", [""])[0]
        options["volume_source"] = form_data.get("volume_source", [None])[0]
        options["volume_destination"] = form_data.get("volume_destination", [None])[0]
        options["volume_csi_plugin_id"] = form_data.get("volume_csi_plugin_id", [None])[
            0
        ]

        if self.memory_limit_in_mb and self.memory_limit_in_mb < options["memory"]:
            err = f"Only {self.memory_limit_in_mb} MB of memory allowed"
            raise ValueError(err)
        if not all(x in self.datacenters for x in options["datacenters"]):
            err = f"Invalid Datacenters list {options['datacenters']}"
            raise ValueError(err)
        if (
            options["volume_type"] == "csi"
            and options["volume_csi_plugin_id"] not in self.csi_plugin_ids
        ):
            err = f"Invalid CSI Plugin {options['volume_csi_plugin_id']}"
            raise ValueError(err)

        return options


def build_nomad_config_from_options(options: NomadSpawner) -> NomadServiceConfig:
    return NomadServiceConfig(
        nomad_addr=AnyHttpUrl(options.nomad_addr),
        nomad_token=options.nomad_token or None,
        tls_config=(
            NomadTLSConfig(
                ca_cert=Path(options.nomad_ca_cert) if options.nomad_ca_cert else None,
                ca_path=Path(options.nomad_ca_path) if options.nomad_ca_path else None,
                client_cert=Path(options.nomad_client_cert),
                client_key=Path(options.nomad_client_key),
                skip_verify=options.nomad_tls_skip_verify,
                tls_server_name=options.nomad_tls_server_name or None,
            )
            if options.nomad_client_key
            else None
        ),
    )


def build_consul_config_from_options(options: NomadSpawner) -> ConsulServiceConfig:
    return ConsulServiceConfig(
        consul_http_addr=AnyHttpUrl(options.consul_http_addr),
        consul_http_token=options.consul_http_token or None,
        tls_config=(
            ConsulTLSConfig(
                ca_cert=(
                    Path(options.consul_ca_cert) if options.consul_ca_cert else None
                ),
                ca_path=(
                    Path(options.consul_ca_path) if options.consul_ca_path else None
                ),
                client_cert=Path(options.consul_client_cert),
                client_key=Path(options.consul_client_key),
                skip_verify=options.consul_tls_skip_verify,
                tls_server_name=options.consul_tls_server_name or None,
            )
            if options.consul_client_key
            else None
        ),
    )


def build_ssl_context(
    tls_config: Union[NomadTLSConfig, ConsulTLSConfig, None],
) -> Union[bool, ssl.SSLContext]:
    """Build the `verify` argument for httpx from a TLS config.

    httpx >= 0.28 deprecated the `cert=` and `verify=<path>` arguments in favour
    of passing a fully configured `ssl.SSLContext`.
    """
    if tls_config is None:
        return True

    if not tls_config.skip_verify and (tls_config.ca_cert or tls_config.ca_path):
        context = ssl.create_default_context(
            cafile=(str(tls_config.ca_cert.resolve()) if tls_config.ca_cert else None),
            capath=(str(tls_config.ca_path.resolve()) if tls_config.ca_path else None),
        )
    else:
        # Kept for backwards compatibility: without a custom CA the server
        # certificate is not verified.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

    context.load_cert_chain(
        certfile=str(tls_config.client_cert.resolve()),
        keyfile=str(tls_config.client_key.resolve()),
    )
    return context


def build_nomad_httpx_client(config: NomadServiceConfig) -> AsyncClient:
    client = AsyncClient(
        base_url=str(config.nomad_addr),
        verify=build_ssl_context(config.tls_config),
        headers={"X-Nomad-Token": config.nomad_token} if config.nomad_token else None,
    )
    return client


def build_consul_httpx_client(config: ConsulServiceConfig) -> AsyncClient:
    client = AsyncClient(
        base_url=str(config.consul_http_addr),
        verify=build_ssl_context(config.tls_config),
        headers=(
            {"X-Consul-Token": config.consul_http_token}
            if config.consul_http_token
            else None
        ),
    )
    return client
