"""CONTROL360 · Mantener sesión iniciada 30 días.

Se activa desde el WSGI, sin tocar app.py:

    import sys
    sys.path.insert(0, "/home/Habita360/control360/control360_sesion")
    import recordar_sesion
    recordar_sesion.activar(application)   # el objeto Flask de CONTROL360

Qué hace:
- Las sesiones duran 30 días (antes se borraban al cerrar el navegador).
- Cada vez que el usuario entra, los 30 días vuelven a empezar: si usa el
  sistema seguido, nunca le vuelve a pedir la clave.
- El botón Salir sigue funcionando igual (borra la sesión).
- La cookie va solo por HTTPS y no la puede leer JavaScript.
"""
from datetime import timedelta

from flask import session

DIAS = 30


def activar(app, dias=DIAS):
    # Si el WSGI envuelve la app (middleware), buscar el Flask de adentro.
    flask_app = app
    while not hasattr(flask_app, "before_request") and hasattr(flask_app, "app"):
        flask_app = flask_app.app

    flask_app.config.update(
        PERMANENT_SESSION_LIFETIME=timedelta(days=dias),
        SESSION_REFRESH_EACH_REQUEST=True,
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )

    @flask_app.after_request
    def _c360_mantener_sesion(respuesta):
        # Solo cuando ya hay alguien dentro (la sesión tiene datos).
        # Va en after_request para que también cubra el momento del login.
        if session and not session.permanent:
            session.permanent = True
        return respuesta

    return flask_app
