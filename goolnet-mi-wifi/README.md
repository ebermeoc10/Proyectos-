# Mi WiFi Goolnet

App para que cada cliente de Goolnet administre **su propio** WiFi desde el
celular: ver quién está conectado, bloquear equipos desconocidos y cambiar la
clave del WiFi. Funciona desde datos móviles (no necesita estar en el WiFi),
porque la app habla con tu backend y tu backend administra las ONT Huawei por
TR-069 a través de GenieACS.

```
Cliente (PWA) ──HTTPS──> Backend FastAPI ──NBI──> GenieACS ──TR-069──> ONT Huawei
```

## Qué incluye

- **acs/** — GenieACS (ACS TR-069) con Docker + script de provisión Huawei.
- **backend/** — API FastAPI con login de cliente y 3 acciones (conectados,
  bloquear, cambiar WiFi).
- **frontend/** — PWA con marca Goolnet, instalable en el celular.

## Despliegue en el Contabo (resumen)

**1) Levantar GenieACS**
```bash
cd acs
cp .env.example .env && nano .env     # pon un secreto largo
docker compose up -d
```
Apunta las ONT Huawei al ACS: `http://TU_IP:7547/` (ver `acs/README-ACS.md`).

**2) Backend**
```bash
cd ../backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export SESSION_SECRET=$(openssl rand -hex 32)
cp clients.example.json clients.json
uvicorn main:app --host 127.0.0.1 --port 8000
```

**3) Dar de alta un cliente** (lo mapea a su ONT)
```bash
python alta_cliente.py 0700000000 1234 48575443-HG8145X6-485754430000XXXX
```
El `device_id` lo ves en la UI de GenieACS cuando la ONT reporta.

**4) Nginx + HTTPS** delante del backend (sirve la PWA y la API en un dominio,
ej. `miwifi.goolnet.ec`). El backend ya publica la PWA en `/` y la API en
`/api/...`.

## Equipo real de Goolnet

- **ONU de la mayoría:** Huawei **HG8145X6-10** (Wi-Fi 6, doble banda).
- **OLT:** las ONU se ven en CONTROL360 (ej. puerto PON 0/1/10, serie tipo
  `485754430000XXXX`).

## Puntos a ajustar (importante)

1. **Índices WLAN** (2.4/5 GHz) ya quedaron puestos para el HG8145X6 (1 y 5)
   en `backend/config.py`. Se confirman solos en cuanto la primera ONU reporte
   al GenieACS. El **bloqueo por MAC** usa extensiones `X_HW_*` que se terminan
   de afinar con una ONU reportando (5-10 min).
2. **Bloqueo por MAC:** si tu firmware no expone el filtro MAC por TR-069, la
   app igual saca al desconocido con "cambiar clave". El bloqueo fino lo
   activamos cuando confirmemos los parámetros `X_HW_*` de tus equipos.
3. **Clientes en modo bridge:** no aplican (su WiFi lo da otro router). Esta
   app cubre los Huawei en modo router.
4. **Login:** hoy usa un `clients.json`. Para producción lo conectamos a la
   base de clientes de tu sistema ISP para que el alta sea automática.

## Siguiente paso
Pon una ONT Huawei de prueba a reportar al GenieACS y me pasas el modelo
exacto; con eso dejo clavados los parámetros de WLAN y de bloqueo y queda
lista para tus ~450 clientes.
