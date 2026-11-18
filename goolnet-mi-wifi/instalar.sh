#!/usr/bin/env bash
#
# Instalador "Mi WiFi Goolnet" para un VPS Ubuntu/Debian (Contabo).
# Levanta GenieACS + backend FastAPI + Nginx con HTTPS, todo de una.
#
# USO (en la consola del Contabo, como root):
#   DOMINIO=miwifi.goolnet.ec  EMAIL=tu@correo.com  bash instalar.sh
#
# Requisito previo: que el dominio/subdominio ya apunte (DNS tipo A) a la IP
# pública del Contabo. Si aún no, el paso de HTTPS se salta y lo corres luego.

set -euo pipefail

DOMINIO="${DOMINIO:-}"
EMAIL="${EMAIL:-}"
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
BACK_DIR="$APP_DIR/backend"
ACS_DIR="$APP_DIR/acs"

log(){ echo -e "\n\033[1;36m==> $*\033[0m"; }

if [[ $EUID -ne 0 ]]; then echo "Corre como root (sudo)."; exit 1; fi

# ---------------------------------------------------------------------------
log "0/6  Chequeo de puertos (para no chocar con lo que ya corre)"
EN_USO=""
for p in 80 443 7547 7557 7567 8010 3000; do
  if ss -ltn 2>/dev/null | grep -q ":$p "; then EN_USO="$EN_USO $p"; fi
done
if [[ -n "$EN_USO" ]]; then
  echo "AVISO: estos puertos ya están ocupados en este servidor:$EN_USO"
  echo "El 80/443 los comparte Nginx sin problema. Pero si 7547/7557/7567/8010/3000"
  echo "están tomados por otra app (p.ej. las radios), avísame antes de seguir para"
  echo "cambiarlos y no interrumpir nada. (Ctrl+C para parar; Enter para continuar.)"
  read -r _ || true
fi

# ---------------------------------------------------------------------------
log "1/6  Paquetes base"
apt-get update -y
apt-get install -y ca-certificates curl gnupg python3 python3-venv python3-pip nginx openssl iproute2

# ---------------------------------------------------------------------------
log "2/6  Docker (si falta)"
if ! command -v docker >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME:-jammy} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi
systemctl enable --now docker

# ---------------------------------------------------------------------------
log "3/6  GenieACS (Docker)"
if [[ ! -f "$ACS_DIR/.env" ]]; then
  echo "GENIEACS_UI_JWT_SECRET=$(openssl rand -hex 32)" > "$ACS_DIR/.env"
fi
( cd "$ACS_DIR" && docker compose up -d )

# ---------------------------------------------------------------------------
log "4/6  Backend FastAPI (venv + systemd)"
python3 -m venv "$BACK_DIR/venv"
"$BACK_DIR/venv/bin/pip" install --upgrade pip
"$BACK_DIR/venv/bin/pip" install -r "$BACK_DIR/requirements.txt"

[[ -f "$BACK_DIR/clients.json" ]] || echo "{}" > "$BACK_DIR/clients.json"
SESSION_SECRET="$(openssl rand -hex 32)"

cat > /etc/systemd/system/miwifi.service <<EOF
[Unit]
Description=Mi WiFi Goolnet backend
After=network.target docker.service

[Service]
WorkingDirectory=$BACK_DIR
Environment=SESSION_SECRET=$SESSION_SECRET
Environment=GENIEACS_NBI=http://127.0.0.1:7557
ExecStart=$BACK_DIR/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8010
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now miwifi.service

# ---------------------------------------------------------------------------
log "5/6  Nginx (sin tocar lo que ya corre, p.ej. las radios)"
# Server block SOLO para el subdominio miwifi. No se borra ningún otro sitio,
# así las radios y demás siguen igual. Requiere un DOMINIO propio.
if [[ -z "$DOMINIO" ]]; then
  echo "AVISO: sin DOMINIO no creo el sitio de Nginx para no chocar con lo que"
  echo "ya sirve este servidor. Vuelve a correr con DOMINIO=miwifi.tudominio.com"
else
  cat > /etc/nginx/sites-available/miwifi <<EOF
server {
    listen 80;
    server_name ${DOMINIO};

    location /api/ {
        proxy_pass http://127.0.0.1:8010;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
    location / {
        proxy_pass http://127.0.0.1:8010;
        proxy_set_header Host \$host;
    }
}
EOF
  ln -sf /etc/nginx/sites-available/miwifi /etc/nginx/sites-enabled/miwifi
  # NO se borra el sitio default ni ningún otro: las radios quedan intactas.
  nginx -t && systemctl reload nginx
fi

# ---------------------------------------------------------------------------
log "6/6  HTTPS"
if [[ -n "$DOMINIO" && -n "$EMAIL" ]]; then
  apt-get install -y certbot python3-certbot-nginx
  certbot --nginx -d "$DOMINIO" --non-interactive --agree-tos -m "$EMAIL" --redirect || \
    echo "Certbot no pudo emitir aún (revisa que el DNS apunte al Contabo). Reintenta: certbot --nginx -d $DOMINIO"
else
  echo "Sin DOMINIO/EMAIL: queda en HTTP. Cuando el DNS apunte, corre:"
  echo "  certbot --nginx -d TU_DOMINIO -m TU_CORREO --agree-tos --redirect"
fi

cat <<FIN

============================================================
  LISTO.  Mi WiFi Goolnet está corriendo.
------------------------------------------------------------
  App del cliente:   http://${DOMINIO:-IP_DEL_CONTABO}/
  UI de GenieACS:    http://127.0.0.1:3000  (por túnel SSH)
  NBI (interno):     http://127.0.0.1:7557

  FALTA (una vez):
  1) Apuntar las ONU Huawei al ACS por TR-069:
       ACS URL -> http://IP_PUBLICA_CONTABO:7547/
     (desde el perfil de la OLT o en WAN>TR-069 de la ONU)
  2) Dar de alta un cliente de prueba:
       cd $BACK_DIR && source venv/bin/activate
       python alta_cliente.py CEDULA PIN DEVICE_ID
     (el DEVICE_ID sale en la UI de GenieACS cuando la ONU reporta)
============================================================
FIN
