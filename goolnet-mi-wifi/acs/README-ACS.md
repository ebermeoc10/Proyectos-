# GenieACS — ACS para las ONT Huawei de Goolnet

GenieACS es el servidor TR-069 que administra las ONT. Tu backend NO habla
con las ONT directamente: habla con GenieACS por su API (NBI, puerto 7557).

## 1. Levantar GenieACS en el Contabo

```bash
cd acs
cp .env.example .env
nano .env          # pon un secreto largo (openssl rand -hex 32)
docker compose up -d
```

Comprueba:
```bash
docker compose ps
curl http://127.0.0.1:7557/devices    # debe responder [] al inicio
```

La UI de administración queda en http://127.0.0.1:3000 (ábrela por túnel SSH
o detrás de tu VPN; no la expongas directa a internet).

## 2. Apuntar las ONT Huawei al ACS

Cada ONT debe reportar por TR-069 a tu servidor. En el equipo Huawei (o
empujado desde el perfil de la OLT) configura:

- **URL del ACS (ACS URL):** `http://TU_IP_PUBLICA:7547/`
- **Usuario / clave del ACS:** los que definas (ej. `goolnet` / clave fuerte)
- **Periodic Inform:** activado, cada 300 s
- **Connection Request:** usuario/clave (para que el ACS pueda "despertar" la ONT)

En muchos Huawei esto está en WAN > TR-069, o se manda por el OLT en el
service-profile. Apenas la ONT informe, aparece en la UI de GenieACS.

## 3. Script de provisión

`genieacs-provision.js` es el script que GenieACS ejecuta en cada inform.
Cárgalo en GenieACS > Admin > Provisions con el nombre `default`, y crea un
Virtual Parameter si quieres exponer datos cómodos. Sirve para refrescar
automáticamente la tabla de hosts y la config WLAN en cada conexión.

## Notas de seguridad
- El NBI (7557) queda escuchando solo en 127.0.0.1. Tu backend corre en el
  mismo servidor y lo llama por localhost. Nunca lo abras a internet.
- Pon el 7547 (CWMP) detrás de tu firewall permitiendo solo el rango de IP de
  tus clientes si es posible.
