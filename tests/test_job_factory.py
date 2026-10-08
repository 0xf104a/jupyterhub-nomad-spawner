from unittest.mock import Mock

import pytest
from jupyterhub.objects import Hub
from traitlets.config import Config

from jupyterhub_nomad_spawner.job_factory import (
    JobData,
    JobVolumeData,
    ServiceProvider,
    VolumeType,
    create_job,
)
from jupyterhub_nomad_spawner.spawner import NomadSpawner

from .utils import fixture_content, update_fixture


def test_create_job(update_job_fixtures: bool):
    job = create_job(
        JobData(
            job_name="jupyter-notebook-123",
            service_name="jupyter-notebook-123",
            username="myname",
            notebook_name="mynotebook",
            env={"foo": "bar", "some_list": '["a", "b", "c"]'},
            datacenters=["dc1", "dc2"],
            args=["--arg1", "--arg2"],
            image="quay.io/jupyter/minimal-notebook",
            cpu=500,
            memory=512,
            service_provider=ServiceProvider.consul,
        )
    )
    if update_job_fixtures:
        update_fixture("test_create_job", job)
    assert job == fixture_content("test_create_job")


def test_create_job_with_host_volume(update_job_fixtures: bool):
    job = create_job(
        JobData(
            job_name="jupyter-notebook-123",
            service_name="jupyter-notebook-123",
            username="myname",
            env={"foo": "bar"},
            datacenters=["dc1", "dc2"],
            args=["--arg1", "--arg2"],
            image="quay.io/jupyter/minimal-notebook",
            cpu=500,
            memory=512,
            service_provider=ServiceProvider.consul,
            volume_data=JobVolumeData(
                type=VolumeType.host,
                source="jupyternotebookhostvolume",
                destination="/home/jovyan/work",
            ),
        )
    )
    if update_job_fixtures:
        update_fixture("test_create_job_with_host_volume", job)
    assert job == fixture_content("test_create_job_with_host_volume")


def test_create_job_with_csi_volume(update_job_fixtures: bool):
    job = create_job(
        JobData(
            job_name="jupyter-notebook-123",
            service_name="jupyter-notebook-123",
            username="myname",
            env={"foo": "bar"},
            datacenters=["dc1", "dc2"],
            args=["--arg1", "--arg2"],
            image="quay.io/jupyter/minimal-notebook",
            cpu=500,
            memory=512,
            service_provider=ServiceProvider.consul,
            namespace="notebooks",
            volume_data=JobVolumeData(
                type=VolumeType.csi,
                source="somecsivolumeid",
                destination="/home/jovyan/work",
            ),
        )
    )
    if update_job_fixtures:
        update_fixture("test_create_job_with_csi_volume", job)
    assert job == fixture_content("test_create_job_with_csi_volume")


def test_create_job_with_ephemeral_disk(update_job_fixtures: bool):
    job = create_job(
        JobData(
            job_name="jupyter-notebook-123",
            service_name="jupyter-notebook-123",
            username="myname",
            env={"foo": "bar"},
            datacenters=["dc1", "dc2"],
            args=["--arg1", "--arg2"],
            image="quay.io/jupyter/minimal-notebook",
            cpu=500,
            memory=512,
            service_provider=ServiceProvider.consul,
            volume_data=JobVolumeData(
                type=VolumeType.ephemeral_disk,
                destination="/home/jovyan/work",
                ephemeral_disk_size=1000,
            ),
        )
    )
    if update_job_fixtures:
        update_fixture("test_create_job_with_ephemeral_disk", job)
    assert job == fixture_content("test_create_job_with_ephemeral_disk")


@pytest.fixture
def hub() -> Hub:
    return Hub(ip="127.0.0.1", port=8081, base_url="/hub/", public_host="127.0.0.1")


class MockUser(Mock):
    hub: Hub
    name = "myname"

    def __init__(self, **kwargs):
        super().__init__()
        for key, value in kwargs.items():
            setattr(self, key, value)

    @property
    def escaped_name(self):
        return self.name

    @property
    def url(self):
        return "/server/name/lab"


@pytest.fixture
def user(hub):
    return MockUser(hub=hub)


@pytest.fixture
def config(monkeypatch):
    cfg = Config()
    cfg.NomadSpawner.base_job_name = "jupyter-notebook"
    cfg.NomadSpawner.service_provider = "consul"

    # slim down env vars to avoid test pollution by the host config
    cfg.NomadSpawner.env_keep = [
        "LANG",
        "LC_ALL",
        "JUPYTERHUB_SINGLEUSER_APP",
    ]
    # ... and pin the kept ones so the rendered job is reproducible
    monkeypatch.setenv("LANG", "C.UTF-8")
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("JUPYTERHUB_SINGLEUSER_APP", raising=False)
    return cfg


def test_spawner_auto_remove_default(user):
    cfg = Config()

    spawner = NomadSpawner(user=user, config=cfg)

    assert spawner.auto_remove_jobs is False


@pytest.mark.parametrize("auto_remove", [True, False])
def test_spawner_auto_remove_set(user, auto_remove):
    cfg = Config()
    cfg.NomadSpawner.auto_remove_jobs = auto_remove

    spawner = NomadSpawner(user=user, config=cfg)

    assert spawner.auto_remove_jobs is auto_remove


def test_spawner_namespace_default(user, monkeypatch):
    monkeypatch.delenv("NOMAD_NAMESPACE", raising=False)
    assert NomadSpawner(user=user, config=Config()).namespace == "default"

    monkeypatch.setenv("NOMAD_NAMESPACE", "notebooks")
    assert NomadSpawner(user=user, config=Config()).namespace == "notebooks"


@pytest.mark.asyncio
async def test_job_factory_default(user, hub, config):
    spawner = NomadSpawner(user=user, hub=hub, config=config)

    # comes from the user form
    spawner.user_options = {
        "datacenters": ["dc1", "dc2"],
        "image": "quay.io/jupyter/minimal-notebook",
        "memory": 512,
    }

    # is generated in the spawners start method
    spawner.notebook_id = "123"

    nomad_service = Mock()
    job = await spawner.job_factory(nomad_service=nomad_service)

    assert job == fixture_content("test_create_job.v2")


class PreConfiguredNomadSpawner(NomadSpawner):
    async def job_factory(self, _) -> str:
        return create_job(
            job_data=JobData(
                job_name=self.job_name,
                username=self.user.name,
                notebook_name=self.name,
                service_provider=ServiceProvider(self.service_provider),
                service_name=self.service_name,
                env=self.get_env(),
                args=self.get_args(),
                image="quay.io/jupyter/minimal-notebook",
                datacenters=["dc1", "dc2"],
                memory=512,
            ),
            job_template_path=self.job_template_path,
        )


@pytest.mark.asyncio
async def test_spawner_job_factory(user, hub, config, update_job_fixtures: bool):
    spawner = PreConfiguredNomadSpawner(user=user, hub=hub, config=config)

    # is generated in the spawners start method
    spawner.notebook_id = "123"

    nomad_service = Mock()
    job = await spawner.job_factory(nomad_service)

    if update_job_fixtures:
        update_fixture("test_create_job.v2", job)
    assert job == fixture_content("test_create_job.v2")


def test_name_rendering_default(user, hub, config):
    # reset to base as fixture uses different base name
    config.NomadSpawner.base_job_name = "jupyterhub-notebook"

    spawner = NomadSpawner(user=user, hub=hub, config=config)

    spawner.notebook_id = "123"

    assert spawner._render_name_template() == "jupyterhub-notebook-123"


# easier than patching or creating an orm spawner
class NamedSpawner(NomadSpawner):
    name: str = "testing-server"


def test_name_rendering_with_custom_template(user, hub, config):
    config.NomadSpawner.name_template = "{{username}}-{{servername}}"

    spawner = NamedSpawner(user=user, hub=hub, config=config)

    spawner.notebook_id = "123"

    assert spawner._render_name_template() == "myname-testing-server"


def test_name_rendering_to_long(user, hub, config):
    config.NomadSpawner.name_template = (
        "{{prefix}}-{{username}}-{{servername}}-{{notebookid}}"
        "-add-some-other-characters-to-break-the-limit"
    )

    spawner = NamedSpawner(user=user, hub=hub, config=config)

    spawner.notebook_id = "123"

    assert spawner._render_name_template() == "jupyter-notebook-123"


def test_name_rendering_not_rfc(user, hub, config):
    # it does not matter where the invalid character comes from
    config.NomadSpawner.name_template = "{{prefix}}@{{username}}"

    spawner = NamedSpawner(user=user, hub=hub, config=config)

    spawner.notebook_id = "123"

    assert spawner._render_name_template() == "jupyter-notebook-123"


@pytest.fixture
def form_spawner(user, hub, config):
    config.NomadSpawner.datacenters = ["dc1", "dc2"]
    config.NomadSpawner.csi_plugin_ids = ["nfs"]
    config.NomadSpawner.mem_limit = "2G"
    return NomadSpawner(user=user, hub=hub, config=config)


def test_options_from_form_is_registered(form_spawner):
    # JupyterHub >= 5 only calls the `options_from_form` trait, make sure our
    # parsing is hooked in (and not the passthrough default)
    form_data = {
        "image": ["quay.io/jupyter/minimal-notebook"],
        "datacenters": ["dc1", "dc2"],
        "memory": ["1024"],
        "volume_type": ["csi"],
        "volume_source": ["jupyter"],
        "volume_destination": ["/home/jovyan/work"],
        "volume_csi_plugin_id": ["nfs"],
    }

    options = form_spawner.run_options_from_form(form_data)

    assert options == {
        "image": "quay.io/jupyter/minimal-notebook",
        "datacenters": ["dc1", "dc2"],
        "memory": 1024,
        "volume_type": "csi",
        "volume_source": "jupyter",
        "volume_destination": "/home/jovyan/work",
        "volume_csi_plugin_id": "nfs",
    }


def test_options_from_form_lite(form_spawner):
    # the lite form only submits the visible/hidden defaults
    form_data = {
        "image": ["quay.io/jupyter/minimal-notebook"],
        "datacenters": ["dc1"],
        "memory": ["1024"],
        "volume_type": [""],
        "volume_source": ["jupyter"],
        "volume_destination": ["/home/jovyan/work"],
    }

    options = form_spawner.run_options_from_form(form_data)

    assert options["volume_type"] == ""
    assert options["volume_csi_plugin_id"] is None


@pytest.mark.parametrize(
    "override",
    [
        {"memory": ["4096"]},
        {"datacenters": ["dc3"]},
        {"volume_type": ["csi"], "volume_csi_plugin_id": ["unknown"]},
    ],
)
def test_options_from_form_validation(form_spawner, override):
    form_data = {
        "image": ["quay.io/jupyter/minimal-notebook"],
        "datacenters": ["dc1"],
        "memory": ["1024"],
        "volume_type": [""],
    }
    form_data.update(override)

    with pytest.raises(ValueError):
        form_spawner.run_options_from_form(form_data)


def test_memory_limit_in_mb(form_spawner):
    assert form_spawner.memory_limit_in_mb == 2048
