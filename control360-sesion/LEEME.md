# CONTROL360 · Mantener sesión iniciada (30 días)

Para que CONTROL360 no pida usuario y clave a cada rato.

## Cómo se instala en PythonAnywhere (sin tocar `app.py`)

1. Subir `recordar_sesion.py` a `/home/Habita360/control360/control360_sesion/`.
2. Respaldar el WSGI: copiar `/var/www/habita360_pythonanywhere_com_wsgi.py` como
   `wsgi_respaldo_sesion.py`.
3. Agregar al final del WSGI (después de que exista `application`):

   ```python
   # --- CONTROL360: mantener sesión iniciada 30 días ---
   sys.path.insert(0, "/home/Habita360/control360/control360_sesion")
   import recordar_sesion
   recordar_sesion.activar(application)
   ```

4. Botón **Reload** en la pestaña Web.

Quienes ya tenían la sesión abierta quedan con los 30 días desde su próxima visita.
El botón **Salir** sigue cerrando la sesión.

Para quitarlo: borrar esas 4 líneas del WSGI y recargar.
