import logging

import httpx
import pytest

from jupyterhub_nomad_spawner.nomad.nomad_service import NomadException, NomadService


@pytest.mark.respx(base_url="http://localhost:4646")
@pytest.mark.asyncio
async def test_register_volume(respx_mock):
    route = respx_mock.put(
        "/v1/volume/csi/volume123/create",
        params={"namespace": "notebooks"},
        json={
            "Volumes": [
                {
                    "AccessMode": "single-node-writer",
                    "AttachmentMode": "file-system",
                    "ID": "volume123",
                    "ExternalID": "volume123",
                    "Name": "volume123",
                    "PluginID": "csi_plugin_1",
                    "RequestedCapabilities": [
                        {
                            "AccessMode": "single-node-writer",
                            "AttachmentMode": "file-system",
                        }
                    ],
                }
            ]
        },
    ).mock(return_value=httpx.Response(200))

    async with httpx.AsyncClient(base_url="http://localhost:4646") as client:
        service = NomadService(
            client=client, log=logging.getLogger("test"), namespace="notebooks"
        )
        await service.create_volume(id="volume123", plugin_id="csi_plugin_1")

    assert route.called


@pytest.mark.respx(base_url="http://localhost:4646")
@pytest.mark.asyncio
async def test_register_existing_volume(respx_mock):
    respx_mock.put(
        "/v1/volume/csi/volume123/create",
        json={
            "Volumes": [
                {
                    "AccessMode": "single-node-writer",
                    "AttachmentMode": "file-system",
                    "ID": "volume123",
                    "ExternalID": "volume123",
                    "Name": "volume123",
                    "PluginID": "csi_plugin_1",
                    "RequestedCapabilities": [
                        {
                            "AccessMode": "single-node-writer",
                            "AttachmentMode": "file-system",
                        }
                    ],
                }
            ]
        },
    ).mock(return_value=httpx.Response(403))

    with pytest.raises(NomadException):
        async with httpx.AsyncClient(base_url="http://localhost:4646") as client:
            service = NomadService(client=client, log=logging.getLogger("test"))
            await service.create_volume(id="volume123", plugin_id="csi_plugin_1")


@pytest.mark.respx(base_url="http://localhost:4646")
@pytest.mark.asyncio
async def test_lookup_service(respx_mock):
    respx_mock.get("/v1/service/my-notebook-service-123").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "Address": "127.0.0.1",
                    "AllocID": "177160af-26f6-619f-9c9f-5e46d1104395",
                    "CreateIndex": 14,
                    "Datacenter": "dc1",
                    "ID": "_nomad-task-177160af-26f6-619f-9c9f-5e46d1104395-redis-example-cache-redis-db",  # noqa: E501
                    "JobID": "example",
                    "ModifyIndex": 24,
                    "Namespace": "default",
                    "NodeID": "7406e90b-de16-d118-80fe-60d0f2730cb3",
                    "Port": 29702,
                    "ServiceName": "my-notebook-service-123",
                    "Tags": ["db", "cache"],
                }
            ],
        )
    )
    async with httpx.AsyncClient(base_url="http://localhost:4646") as client:
        service = NomadService(client=client, log=logging.getLogger("test"))
        address, port = await service.get_service_address(
            service_name="my-notebook-service-123"
        )
        assert address == "127.0.0.1"
        assert port == 29702


def _allocation(task_state: str, failed: bool = False, event_type: str = "Started"):
    return {
        "ID": "177160af-26f6-619f-9c9f-5e46d1104395",
        "CreateTime": 1,
        "TaskStates": {
            "nb": {
                "State": task_state,
                "Failed": failed,
                "Restarts": 0,
                "StartedAt": "2026-10-08T10:00:00Z",
                "FinishedAt": "0001-01-01T00:00:00Z",
                "Events": [
                    {
                        "Type": event_type,
                        "Time": 1,
                        "DisplayMessage": "message",
                        "Details": {},
                        "FailsTask": False,
                        "DriverMessage": "",
                    }
                ],
            }
        },
    }


@pytest.mark.parametrize(
    "allocations,expected",
    [
        ([], "pending"),
        ([_allocation("running")], "running"),
        ([_allocation("dead", failed=True)], "dead"),
        ([_allocation("pending", event_type="Driver")], "starting"),
        ([_allocation("pending", event_type="Received")], "pending"),
    ],
)
@pytest.mark.respx(base_url="http://localhost:4646")
@pytest.mark.asyncio
async def test_task_status(respx_mock, allocations, expected):
    respx_mock.get("/v1/job/jupyter-notebook-123/allocations").mock(
        return_value=httpx.Response(200, json=allocations)
    )
    async with httpx.AsyncClient(base_url="http://localhost:4646") as client:
        service = NomadService(client=client, log=logging.getLogger("test"))
        assert await service.task_status("jupyter-notebook-123") == expected


@pytest.mark.respx(base_url="http://localhost:4646")
@pytest.mark.asyncio
async def test_delete_job_with_purge(respx_mock):
    route = respx_mock.delete(
        "/v1/job/jupyter-notebook-123", params={"namespace": "default", "purge": "true"}
    ).mock(return_value=httpx.Response(200, json={}))

    async with httpx.AsyncClient(base_url="http://localhost:4646") as client:
        service = NomadService(client=client, log=logging.getLogger("test"))
        await service.delete_job("jupyter-notebook-123", purge=True)

    assert route.called
