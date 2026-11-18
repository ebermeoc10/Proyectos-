"""
Backend "Mi WiFi Goolnet" — FastAPI.

Expone a la app del cliente 3 acciones sobre SU ONT Huawei, vía GenieACS:
  - GET  /api/dispositivos   -> quién está conectado
  - POST /api/bloquear       -> bloquear una MAC desconocida
  - POST /api/wifi           -> cambiar nombre y/o clave del WiFi

Arranque:
    pip install -r requirements.txt
    uvicorn main:app --host 127.0.0.1 --port 8000
(Detrás de Nginx con HTTPS. La app PWA se sirve como estático.)
"""

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import os

import config
import auth
from genieacs import GenieACS, parse_hosts, current_ssid

app = FastAPI(title="Mi WiFi Goolnet", version="1.0")
acs = GenieACS()

# CORS por si sirves la PWA desde otro dominio. Ajusta el origen.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- modelos ----------
class LoginIn(BaseModel):
    usuario: str
    pin: str

class BloquearIn(BaseModel):
    mac: str = Field(..., description="MAC a bloquear, formato AA:BB:CC:DD:EE:FF")

class WifiIn(BaseModel):
    ssid: str | None = None
    clave: str | None = Field(None, min_length=8, description="Mínimo 8 caracteres")


# ---------- auth helper ----------
def require_device(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Falta sesión")
    data = auth.verify_token(authorization[7:])
    if not data:
        raise HTTPException(401, "Sesión inválida o vencida")
    return data["device_id"]


# ---------- endpoints ----------
@app.post("/api/login")
async def login(body: LoginIn):
    device_id = auth.verify_login(body.usuario, body.pin)
    if not device_id:
        raise HTTPException(401, "Usuario o PIN incorrecto")
    if not await acs.device_exists(device_id):
        raise HTTPException(409, "Tu equipo aún no reporta al sistema. Intenta más tarde.")
    return {"token": auth.make_token(body.usuario, device_id)}


@app.get("/api/dispositivos")
async def dispositivos(authorization: str | None = Header(default=None)):
    device_id = require_device(authorization)
    # Refresca la tabla de hosts antes de leer.
    try:
        await acs.refresh(device_id, config.HOSTS_TABLE)
    except Exception:
        pass  # si la ONT no responde al toque, devolvemos lo último informado
    device = await acs.get_device(device_id)
    if not device:
        raise HTTPException(404, "Equipo no encontrado")
    hosts = parse_hosts(device)
    return {
        "total": len([h for h in hosts if h["active"]]),
        "dispositivos": hosts,
    }


@app.post("/api/bloquear")
async def bloquear(body: BloquearIn, authorization: str | None = Header(default=None)):
    device_id = require_device(authorization)
    if not config.BLOCK_SUPPORTED:
        raise HTTPException(
            400,
            "Este equipo no soporta bloqueo por MAC. Usa 'cambiar clave' para "
            "sacar al desconocido.",
        )
    values = []
    for idx in config.WLAN_INDEXES:
        values += config.block_params(idx, body.mac)
    await acs.set_values(device_id, values)
    return {"ok": True, "mensaje": f"Se bloqueó {body.mac}"}


@app.post("/api/wifi")
async def cambiar_wifi(body: WifiIn, authorization: str | None = Header(default=None)):
    device_id = require_device(authorization)
    if not body.ssid and not body.clave:
        raise HTTPException(400, "Nada que cambiar")
    values = []
    for idx in config.WLAN_INDEXES:
        if body.ssid:
            values.append((config.ssid_param(idx), body.ssid, "xsd:string"))
        if body.clave:
            for p in config.passphrase_params(idx):
                values.append((p, body.clave, "xsd:string"))
    await acs.set_values(device_id, values)
    return {"ok": True, "mensaje": "WiFi actualizado. Reconecta tus equipos con los nuevos datos."}


@app.get("/api/estado")
async def estado(authorization: str | None = Header(default=None)):
    device_id = require_device(authorization)
    device = await acs.get_device(device_id)
    if not device:
        raise HTTPException(404, "Equipo no encontrado")
    return {
        "ssid": current_ssid(device, config.WLAN_INDEXES[0]),
        "online": True,
    }


# Sirve la PWA (carpeta ../frontend) como estático en la raíz.
_front = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(_front):
    app.mount("/", StaticFiles(directory=_front, html=True), name="front")
