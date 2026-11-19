"""Para correr el módulo solo (pruebas o si se quiere en una app aparte de PythonAnywhere).

    python app_sola.py          -> http://127.0.0.1:5050/tecnicos/
"""
import os
from datetime import timedelta
from flask import Flask, redirect
from tecnicos import bp

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "cambie-esta-clave-secreta")
app.permanent_session_lifetime = timedelta(days=30)
app.register_blueprint(bp, url_prefix="/tecnicos")


@app.route("/")
def inicio():
    return redirect("/tecnicos/")


if __name__ == "__main__":
    app.run(port=5050, debug=True)
