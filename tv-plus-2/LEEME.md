# TV Plus — reproductor IPTV

App para ver TV en vivo, películas y series. El cliente solo escribe **usuario y contraseña**: la URL del servidor va incluida en la app. Se maneja con el control remoto.

**URL del servidor:** está en `www/index.html`, al inicio del script, en la línea `var SERVER_URL = '...';`. Si se deja vacía, la app vuelve a pedir la URL (y permite listas M3U).

## Qué trae
- Televisión en vivo por categorías, con guía de programación (Ahora / Después)
- Películas y Series (temporadas y episodios)
- Favoritos (botón «Agregar a favoritos» o botón **rojo** del control)
- Búsqueda en canales, películas y series
- Recuerda al cliente: la próxima vez entra directo
- Muestra la fecha de vencimiento y las conexiones de la cuenta
- En el reproductor: ▲▼ o CH+/CH− cambian de canal, OK muestra información, ATRÁS sale
- Si un canal no carga en HLS (m3u8), prueba solo con TS; también se puede elegir en **Cuenta**

## Carpetas
| Carpeta | Para qué |
|---|---|
| `www/index.html` | La app (un solo archivo). El nombre está en `APP_NAME` y la URL en `SERVER_URL`, al inicio del script |
| `samsung-tizen/` | Proyecto listo para Samsung (Tizen 5 / modelos 2019 en adelante) |
| `lg-webos/` | Proyecto listo para LG (webOS 5 / modelos 2020 en adelante) |
| `android-tv/` | Proyecto Android TV / TV Box / Fire TV (Android 5 en adelante) |
| `.github/workflows/` | Compila el APK de Android automáticamente en GitHub |
| `assets/` | Íconos y banner |

Si cambias `www/index.html`, cópialo también a `lg-webos/` y `android-tv/app/src/main/assets/www/`. En `samsung-tizen/` el código va separado en `app.js` y `app.css` (Samsung bloquea el código dentro del HTML): copia ahí el contenido de `<script>` y `<style>`.

## Cómo instalar
**Android TV / TV Box (lo más fácil):**
1. Sube esta carpeta a un repositorio de GitHub.
2. GitHub compila solo el APK (pestaña *Actions* → *Compilar APK TV Plus* → descargar *TVPlus-apk*).
3. Instala el APK en el TV Box con «Downloader» o una memoria USB.
   También se puede abrir `android-tv/` con Android Studio en la Mac y darle *Run*.

**Samsung:** con Tizen Studio (en la Mac): *File → Import → Tizen → Tizen Project* con la carpeta `samsung-tizen`, crear un certificado de Samsung, activar el *Modo desarrollador* del televisor y darle *Run As → Tizen Web Application*. Para publicarla en la tienda de Samsung hace falta una cuenta de vendedor en Samsung Apps TV Seller Office.

**LG:** instalar las *webOS CLI* (`npm install -g @webos-tools/cli`), luego `ares-package lg-webos` (genera el `.ipk`) y `ares-install` hacia un televisor con la app *Developer Mode* activada. Para la tienda de LG se necesita cuenta en LG Seller Lounge.

## Importante
- La app es solo un **reproductor**: no trae canales. Los canales los pone el servidor IPTV de cada cliente; usa servidores y listas con derechos de transmisión.
- En la vista previa web (navegador) solo funcionan servidores **https**. Instalada en el televisor funciona con cualquier servidor (http o https).
