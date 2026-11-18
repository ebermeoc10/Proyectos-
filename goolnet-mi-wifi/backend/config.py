"""
Configuración de parámetros TR-069 para las ONT Huawei de Goolnet.

MODELO DE LA MAYORÍA: Huawei HG8145X6-10 (Wi-Fi 6, doble banda).
Modelo de datos: TR-098 / InternetGatewayDevice.

Índices de WLAN en el HG8145X6 (doble banda):
    WLANConfiguration.1  -> 2.4 GHz
    WLANConfiguration.5  -> 5 GHz
(En los Huawei HG8145/EG8145 este es el mapeo estándar. Se confirma solo
apenas la primera ONU reporte al GenieACS; si llegara a diferir, se cambia
únicamente WLAN_INDEXES aquí abajo.)

Para bloquear por MAC, Huawei usa extensiones propias (X_HW_*) que cambian
entre firmwares. Por eso el bloqueo está parametrizado abajo y, como método
100% garantizado para "sacar al desconocido", la app ofrece cambiar la clave
(desconecta a todos y el dueño vuelve a entrar con la nueva).
"""

import os

# URL del NBI de GenieACS (en el mismo servidor, por localhost).
GENIEACS_NBI = os.environ.get("GENIEACS_NBI", "http://127.0.0.1:7557")

# Índices de WLAN a tocar al cambiar SSID/clave (2.4 y 5 GHz).
WLAN_INDEXES = [int(x) for x in os.environ.get("WLAN_INDEXES", "1,5").split(",")]

# Prefijo del modelo de datos.
IGD = "InternetGatewayDevice"

# --- Lectura: tabla de dispositivos conectados (hosts) ---
HOSTS_TABLE = f"{IGD}.LANDevice.1.Hosts.Host"
# Campos que leemos de cada host.
HOST_FIELDS = {
    "hostname": "HostName",
    "ip": "IPAddress",
    "mac": "MACAddress",
    "active": "Active",
    "iface": "InterfaceType",
}

# --- Lectura: clientes asociados por WiFi (para contarlos por banda) ---
def wlan_assoc_table(idx: int) -> str:
    return f"{IGD}.LANDevice.1.WLANConfiguration.{idx}.AssociatedDevice"

# --- Escritura: SSID y clave ---
def ssid_param(idx: int) -> str:
    return f"{IGD}.LANDevice.1.WLANConfiguration.{idx}.SSID"

def passphrase_params(idx: int):
    # Distintos firmwares aceptan uno u otro; mandamos ambos y el que exista aplica.
    return [
        f"{IGD}.LANDevice.1.WLANConfiguration.{idx}.KeyPassphrase",
        f"{IGD}.LANDevice.1.WLANConfiguration.{idx}.PreSharedKey.1.KeyPassphrase",
        f"{IGD}.LANDevice.1.WLANConfiguration.{idx}.PreSharedKey.1.PreSharedKey",
    ]

# --- Escritura: bloqueo por MAC (extensión Huawei, AJUSTAR por modelo) ---
# Activa el filtro MAC en modo "lista negra" y agrega la MAC.
# Si tu modelo no soporta estos parámetros, deja BLOCK_SUPPORTED = False y la
# app usará solo el cambio de clave como método de expulsión.
BLOCK_SUPPORTED = os.environ.get("BLOCK_SUPPORTED", "true").lower() == "true"

def block_params(idx: int, mac: str):
    """Devuelve lista de (parametro, valor, tipo) para bloquear una MAC."""
    base = f"{IGD}.LANDevice.1.WLANConfiguration.{idx}"
    return [
        (f"{base}.X_HW_WlanMacFilterMode", "2", "xsd:string"),     # 2 = lista negra (modelo-dependiente)
        (f"{base}.X_HW_WlanMacFilterEnable", "1", "xsd:string"),
        (f"{base}.X_HW_WlanMacFilterList", mac, "xsd:string"),
    ]
