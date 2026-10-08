import logging
from pathlib import Path

from jupyterhub_nomad_spawner.job_options_factory import create_form

log = logging.getLogger(__name__)

FIXTURE = Path(__file__).parent / "fixtures" / "test_create_form.html"


def test_create_form(update_job_options_fixtures):
    datacenters = ["dc1", "dc2"]
    common_images = ["common_image1", "common_image2"]
    csi_plugin_ids = ["csi_plugin_id1", "csi_plugin_id2"]
    memory_limit = 1024
    html = create_form(datacenters, common_images, csi_plugin_ids, memory_limit)

    if update_job_options_fixtures:
        log.warning("Updating job options fixtures")
        FIXTURE.write_text(html)

    # compare html against fixture
    assert html == FIXTURE.read_text()


def test_create_form_lite():
    html = create_form(["dc1"], ["image1"], ["csi1"], 512, lite_form=True)

    # the lite form hides everything but image and datacenters ...
    assert 'name="image"' in html
    assert 'name="datacenters"' in html
    assert 'id="volume_type_csi"' not in html
    assert 'id="volume_type_host"' not in html
    # ... and still submits a memory value that respects the limit
    assert 'name="memory" min="8"\n           value="512"' in html


def test_create_form_without_csi_plugins():
    html = create_form(["dc1"], ["image1"], None)

    assert 'name="volume_csi_plugin_id"' not in html
    assert "max=" not in html
