"""Cliente mínimo del NBI (API) de GenieACS."""

import json
import urllib.parse
import httpx

import config


class GenieACS:
    def __init__(self, base_url: str = config.GENIEACS_NBI, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def _client(self):
        return httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)

    async def get_device(self, device_id: str) -> dict | None:
        """Devuelve el objeto de la ONT (con sus parámetros ya informados)."""
        query = urllib.parse.quote(json.dumps({"_id": device_id}))
        async with await self._client() as c:
            r = await c.get(f"/devices/?query={query}")
            r.raise_for_status()
            data = r.json()
            return data[0] if data else None

    async def device_exists(self, device_id: str) -> bool:
        return (await self.get_device(device_id)) is not None

    async def _task(self, device_id: str, body: dict, connection_request: bool = True):
        """Encola una tarea en la ONT. connection_request intenta ejecutarla ya."""
        suffix = "?connection_request" if connection_request else ""
        async with await self._client() as c:
            r = await c.post(f"/devices/{urllib.parse.quote(device_id)}/tasks{suffix}",
                             json=body)
            r.raise_for_status()
            return r.json() if r.content else {}

    async def refresh(self, device_id: str, parameter: str):
        """Pide a la ONT que vuelva a informar un subárbol (ej. los hosts)."""
        return await self._task(device_id, {
            "name": "refreshObject",
            "objectName": parameter,
        })

    async def set_values(self, device_id: str, values: list[tuple[str, str, str]]):
        """values: lista de (parametro, valor, tipo xsd)."""
        return await self._task(device_id, {
            "name": "setParameterValues",
            "parameterValues": [[p, v, t] for (p, v, t) in values],
        })


def _leaf(node, field):
    """Lee el _value de un campo dentro de un nodo del árbol GenieACS."""
    try:
        return node[field]["_value"]
    except (KeyError, TypeError):
        return None


def parse_hosts(device: dict) -> list[dict]:
    """Extrae la tabla de hosts (dispositivos conectados) del objeto device."""
    out = []
    try:
        table = device
        for part in config.HOSTS_TABLE.split("."):
            table = table[part]
    except (KeyError, TypeError):
        return out

    for key, node in table.items():
        if not key.isdigit():
            continue
        host = {}
        for nice, raw in config.HOST_FIELDS.items():
            host[nice] = _leaf(node, raw)
        # Normaliza "activo".
        host["active"] = str(host.get("active")).lower() in ("true", "1")
        if host.get("mac"):
            out.append(host)
    return out


def current_ssid(device: dict, idx: int) -> str | None:
    node = device
    try:
        for part in config.ssid_param(idx).split("."):
            node = node[part]
        return node["_value"]
    except (KeyError, TypeError):
        return None
