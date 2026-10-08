import ssl
from pathlib import Path

import pytest
from certipy import Certipy

from jupyterhub_nomad_spawner.consul.consul_service import (
    ConsulServiceConfig,
    ConsulTLSConfig,
)
from jupyterhub_nomad_spawner.nomad.nomad_service import (
    NomadServiceConfig,
    NomadTLSConfig,
)
from jupyterhub_nomad_spawner.spawner import (
    build_consul_httpx_client,
    build_nomad_httpx_client,
    build_ssl_context,
)


@pytest.fixture
def certs(tmp_path):
    """A CA and a client certificate signed by it (certipy ships with jupyterhub)"""
    certipy = Certipy(store_dir=str(tmp_path))
    ca = certipy.create_ca("nomad-ca")
    client = certipy.create_signed_pair("client", "nomad-ca")
    return {
        "ca_cert": Path(ca["files"]["cert"]),
        "client_cert": Path(client["files"]["cert"]),
        "client_key": Path(client["files"]["key"]),
    }


def test_build_ssl_context_without_tls_config():
    assert build_ssl_context(None) is True


def test_build_ssl_context_with_ca(certs):
    context = build_ssl_context(NomadTLSConfig(**certs))

    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert any(
        cert["subject"][-1][0][1] == "nomad-ca"
        for cert in context.get_ca_certs()
        if cert["subject"]
    )


def test_build_ssl_context_with_ca_path(certs):
    context = build_ssl_context(
        ConsulTLSConfig(
            ca_path=certs["ca_cert"].parent,
            client_cert=certs["client_cert"],
            client_key=certs["client_key"],
        )
    )

    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_build_ssl_context_skip_verify(certs):
    context = build_ssl_context(NomadTLSConfig(**certs, skip_verify=True))

    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_NONE
    assert context.check_hostname is False


def test_build_ssl_context_without_ca_does_not_verify(certs):
    # backwards compatible behaviour: client cert but no CA -> no verification
    context = build_ssl_context(
        NomadTLSConfig(client_cert=certs["client_cert"], client_key=certs["client_key"])
    )

    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_NONE


@pytest.mark.asyncio
async def test_build_nomad_httpx_client(certs):
    config = NomadServiceConfig(
        nomad_addr="https://nomad.example.org:4646",
        nomad_token="secret",
        tls_config=NomadTLSConfig(**certs),
    )

    async with build_nomad_httpx_client(config) as client:
        assert str(client.base_url) == "https://nomad.example.org:4646/"
        assert client.headers["X-Nomad-Token"] == "secret"


@pytest.mark.asyncio
async def test_build_consul_httpx_client_defaults():
    async with build_consul_httpx_client(ConsulServiceConfig()) as client:
        assert str(client.base_url) == "http://localhost:8500/"
        assert "X-Consul-Token" not in client.headers
