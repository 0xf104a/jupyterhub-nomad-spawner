from logging import Logger, LoggerAdapter
from pathlib import Path
from typing import Any, List, Optional, Union

from attrs import define
from httpx import AsyncClient
from pydantic import AnyHttpUrl, BaseModel


class ConsulTLSConfig(BaseModel):
    ca_cert: Optional[Path] = None
    ca_path: Optional[Path] = None
    client_cert: Path
    client_key: Path
    skip_verify: bool = False
    tls_server_name: Optional[str] = None


class ConsulServiceConfig(BaseModel):
    consul_http_addr: AnyHttpUrl = AnyHttpUrl("http://localhost:8500")
    consul_http_token: Optional[str] = None
    tls_config: Optional[ConsulTLSConfig] = None


class ConsulException(Exception):
    pass


@define
class ConsulService:
    client: AsyncClient

    log: Union[LoggerAdapter, Logger]

    async def health_service(self, service_name: str) -> List[Any]:
        result = await self.client.get(
            f"/v1/health/service/{service_name}",
        )
        if result.is_error:
            raise ConsulException(f"Error getting service: {result.text}")
        return result.json()
