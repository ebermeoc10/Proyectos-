# CONTROL360 · Técnicos Orange

Módulo para seguir a los técnicos de Orange en campo.

- **Panel web** (`servidor/`): mapa en vivo, paradas de 15 min o más, recorrido del día,
  órdenes de trabajo con tiempo en cada casa, alertas (GPS apagado, batería baja, sin señal,
  paradas fuera de una orden) y ajustes de horario.
- **App Android** (`android/`): el técnico entra con usuario y PIN; la app manda la ubicación
  cada 30 s solo de 8:00 a 18:30 (aunque la pantalla esté apagada) y muestra sus órdenes
  con los botones *Voy en camino → Llegué → Terminé*.

Descarga de la app: https://github.com/ebermeoc10/Proyectos-/releases/download/tecnicos-orange/TecnicosOrange.apk
(se arma sola en GitHub cada vez que cambia algo en `android/`).

## Instalación en PythonAnywhere (ya hecha, 19-nov-2026)

- Archivos en `/home/Habita360/control360/tecnicos_orange/` (`tecnicos.py`, `panel.html`, `entrar.html`;
  la base `tecnicos.db` se crea sola ahí). Respaldo del WSGI original: `wsgi_respaldo.py`.
- Se registra al final de `/var/www/habita360_pythonanywhere_com_wsgi.py` (no se tocó `app.py`):
  - el panel usa el login de CONTROL360 (super o admin de la empresa Orange) y su token csrf;
  - las rutas `/tecnicos/api/...` de la app entran con el token del técnico, por eso se atienden
    antes del control csrf de CONTROL360.
- Panel: https://habita360.pythonanywhere.com/tecnicos/

Para quitarlo: devolver el WSGI al contenido de `wsgi_respaldo.py` y recargar.

## Primer uso

1. Panel → **Técnicos** → agregar cada técnico con usuario y PIN.
2. En el celular del técnico: abrir el enlace de descarga, instalar, entrar con usuario y PIN
   y tocar **Arreglar** hasta que no falte nada (ubicación "Permitir todo el tiempo",
   notificaciones y quitar el ahorro de batería).
3. Panel → **Órdenes** → crear órdenes y asignarlas.

En celulares Xiaomi, Oppo, Huawei y Samsung conviene además fijar la app en recientes
(candado) para que el sistema no la cierre.

## Prueba

```
cd servidor && python prueba.py
```
