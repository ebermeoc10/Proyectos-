# CONTROL360 · Mantener sesión iniciada (30 días)

Para que CONTROL360 no pida usuario y clave a cada rato.

## Instalado en PythonAnywhere (19-nov-2026)

- Antes: `app.py` marcaba la sesión como permanente al entrar, pero con duración de **8 horas**.
- Ahora: bloque al final de `/var/www/habita360_pythonanywhere_com_wsgi.py`
  ("CONTROL360: mantener sesion iniciada 30 dias") que sube la duración a **30 días** y la
  renueva en cada visita. No se tocó `app.py`.
- El botón **Salir** sigue cerrando la sesión.

Para quitarlo: borrar ese bloque del WSGI y pulsar **Reload** en la pestaña Web.

`recordar_sesion.py` es la misma lógica como módulo aparte, por si se quiere usar en otro programa.
