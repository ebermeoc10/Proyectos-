#!/bin/bash
# Instala AzuraCast (servidor de streaming para varias radios) en un servidor Linux de 64 bits.
# Uso, como root:  bash instalar-azuracast.sh
set -e
mkdir -p /var/azuracast && cd /var/azuracast
curl -fsSL https://raw.githubusercontent.com/AzuraCast/AzuraCast/main/docker.sh > docker.sh
chmod a+x docker.sh
./docker.sh install
echo "Listo. Entra a http://IP-DEL-SERVIDOR para crear el usuario administrador."
