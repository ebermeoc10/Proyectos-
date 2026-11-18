"""
Autenticación simple de clientes -> ONT.

Cada cliente entra con un usuario (ej. su cédula o un código Goolnet) y un PIN.
El backend lo mapea al device_id de SU ONT en GenieACS. Un cliente solo puede
ver y tocar su propia ONT.

Esto arranca con un archivo JSON (clients.json). Cuando lo integres con el
sistema ISP real, reemplaza load_clients() por una consulta a tu base de datos.

device_id en GenieACS suele ser:  OUI-ProductClass-SerialNumber
ejemplo:  48575443-HG8145X6-485754430000XXXX
"""

import json
import os
import hashlib
import hmac
import secrets
import time
from pathlib import Path

CLIENTS_FILE = os.environ.get("CLIENTS_FILE", "clients.json")
# Secreto para firmar los tokens de sesión.
SESSION_SECRET = os.environ.get("SESSION_SECRET", secrets.token_hex(32))
SESSION_TTL = 60 * 60 * 8  # 8 horas


def _hash_pin(pin: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 100_000).hex()


def load_clients() -> dict:
    p = Path(CLIENTS_FILE)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def verify_login(usuario: str, pin: str) -> str | None:
    """Devuelve el device_id si las credenciales son válidas, si no None."""
    clients = load_clients()
    rec = clients.get(usuario)
    if not rec:
        return None
    if _hash_pin(pin, rec["salt"]) != rec["pin_hash"]:
        return None
    return rec["device_id"]


def make_token(usuario: str, device_id: str) -> str:
    exp = int(time.time()) + SESSION_TTL
    payload = f"{usuario}|{device_id}|{exp}"
    sig = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}|{sig}"


def verify_token(token: str) -> dict | None:
    try:
        usuario, device_id, exp, sig = token.split("|")
    except ValueError:
        return None
    payload = f"{usuario}|{device_id}|{exp}"
    expected = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    if int(exp) < int(time.time()):
        return None
    return {"usuario": usuario, "device_id": device_id}


# Utilidad para crear credenciales (úsala para dar de alta clientes).
def build_client_record(pin: str, device_id: str) -> dict:
    salt = secrets.token_hex(8)
    return {"salt": salt, "pin_hash": _hash_pin(pin, salt), "device_id": device_id}
