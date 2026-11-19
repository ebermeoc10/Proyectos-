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

## Instalar en PythonAnywhere (CONTROL360)

1. Subir a la carpeta de CONTROL360 los archivos de `servidor/`: `tecnicos.py`, `panel.html`, `entrar.html`.
2. En `flask_app.py`, después de crear `app`:

   ```python
   from tecnicos import bp as tecnicos_bp
   app.register_blueprint(tecnicos_bp, url_prefix="/tecnicos")
   ```
3. En la pestaña **Web** de PythonAnywhere, en *Environment variables* (o al inicio de `flask_app.py`):
   `TECNICOS_CLAVE_PANEL` = clave del panel (por defecto `orange360`, cámbiela).
4. Botón **Reload**. El panel queda en `https://habita360.pythonanywhere.com/tecnicos/`.

La app trae ese servidor por defecto; si cambia, se pone en *Cambiar servidor* al entrar.

Si CONTROL360 ya tiene su propio login, se puede evitar la segunda clave:

```python
from tecnicos import usar_login_de_control360
usar_login_de_control360(lambda: session.get("empresa") == "Orange")  # ajustar a cómo guarda la sesión
```

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
