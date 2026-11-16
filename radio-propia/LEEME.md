# Radio propia: servicio de streaming para radios (Goolnet)

Una app de Android para cada radio cliente: su nombre, logo, colores, su señal en vivo, y botones de WhatsApp y Facebook.
La radio sigue sonando con la pantalla apagada.

## Agregar una radio nueva
1. Crear la carpeta `clientes/<nombre-corto>/` con un `config.json` (copiar el de `demo-goolnet`) y, si hay, `logo.png` cuadrado.
2. En `stream` va el enlace que da AzuraCast para esa radio (por ejemplo `https://radio.goolnet.../listen/<radio>/radio.mp3`).
   Mientras no exista, `buscar` usa el nombre de la radio en el directorio público.
3. `appId` tiene que ser único, por ejemplo `ec.goolnet.radio.lluvia`.
4. Al subir los cambios, GitHub arma los APK solo y quedan en:
   `https://github.com/ebermeoc10/Proyectos-/releases/download/radio-propia/<nombre-corto>.apk`

## Servidor (AzuraCast)
`servidor/instalar-azuracast.sh` lo instala en cualquier Linux de 64 bits con Docker (mínimo 2 GB de RAM, recomendado 4 GB).
Puertos que hay que abrir: 80, 443, 2022 (SFTP) y 8000 en adelante (uno por radio).
En cada radio se usa BUTT (gratis) para mandar el audio de la consola al servidor.
