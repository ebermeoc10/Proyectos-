"""
CONTROL360 · Módulo Técnicos (rastreo de técnicos en campo)
============================================================

Blueprint de Flask para la empresa Orange (ISP) dentro de CONTROL360.

Qué hace
  - Recibe la ubicación de la app Android de cada técnico (solo en horario).
  - Mapa en vivo con el estado de cada técnico (en movimiento, parado, sin señal,
    GPS apagado) y la batería de su celular.
  - Detecta paradas (quieto 15 min o más) y muestra el recorrido del día.
  - Órdenes de trabajo: se asignan a un técnico, que marca "Llegué" y "Terminé";
    el sistema calcula cuánto se demoró en cada casa.
  - Alertas: GPS apagado, batería baja, técnico sin señal.

Cómo se conecta a CONTROL360 (en el flask_app.py de PythonAnywhere):

    from tecnicos import bp as tecnicos_bp
    app.register_blueprint(tecnicos_bp, url_prefix="/tecnicos")

Y queda en  https://SU-DOMINIO/tecnicos/

Todo se guarda en un archivo SQLite propio (tecnicos.db, al lado de este archivo,
o donde diga la variable de entorno TECNICOS_DB). No toca la base de CONTROL360.
"""

import json
import math
import os
import secrets
import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import (Blueprint, current_app, g, jsonify, redirect, request,
                   session, url_for, Response)
from werkzeug.security import check_password_hash, generate_password_hash

AQUI = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("TECNICOS_DB", os.path.join(AQUI, "tecnicos.db"))
EMPRESA = os.environ.get("TECNICOS_EMPRESA", "Orange")
# Clave del panel. Si CONTROL360 ya tiene su login, ver usar_login_de_control360().
CLAVE_PANEL = os.environ.get("TECNICOS_CLAVE_PANEL", "orange360")
APK_URL = os.environ.get(
    "TECNICOS_APK_URL",
    "https://github.com/ebermeoc10/Proyectos-/releases/download/tecnicos-orange/TecnicosOrange.apk")

TZ = timezone(timedelta(hours=-5))  # Ecuador continental, sin horario de verano

RADIO_PARADA_M = 80          # metros: dentro de este radio se considera "quieto"
SIN_SENAL_MIN = 10           # minutos sin reportar (en horario) => "sin señal"
BATERIA_BAJA = 15            # %
RADIO_ORDEN_M = 150          # una parada a menos de esto de una orden cuenta como "en la orden"

AJUSTES_DEFECTO = {
    "hora_inicio": "08:00",
    "hora_fin": "18:30",
    "dias": [0, 1, 2, 3, 4, 5, 6],   # 0 = lunes ... 6 = domingo
    "minutos_parada": 15,
    "intervalo_seg": 30,             # cada cuánto manda ubicación la app
}

bp = Blueprint("tecnicos", __name__)

_chequeo_admin = None  # función externa opcional (login de CONTROL360)
_url_login = None


def usar_login_de_control360(funcion, url_login="/login"):
    """Si CONTROL360 ya tiene login, pásale una función que devuelva True cuando
    el usuario actual es administrador de Orange. Así el panel no pide otra clave.

        from tecnicos import usar_login_de_control360
        usar_login_de_control360(lambda: session.get("empresa") == "Orange")
    """
    global _chequeo_admin, _url_login
    _chequeo_admin = funcion
    _url_login = url_login


# ----------------------------------------------------------------- base de datos

ESQUEMA = """
CREATE TABLE IF NOT EXISTS tecnicos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    usuario TEXT NOT NULL UNIQUE,
    pin_hash TEXT NOT NULL,
    telefono TEXT DEFAULT '',
    color TEXT DEFAULT '',
    activo INTEGER DEFAULT 1,
    token_hash TEXT,
    creado INTEGER
);
CREATE TABLE IF NOT EXISTS puntos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tecnico_id INTEGER NOT NULL,
    ts INTEGER NOT NULL,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    precision REAL,
    velocidad REAL,
    bateria INTEGER,
    cargando INTEGER
);
CREATE INDEX IF NOT EXISTS ix_puntos ON puntos(tecnico_id, ts);
CREATE TABLE IF NOT EXISTS eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tecnico_id INTEGER NOT NULL,
    ts INTEGER NOT NULL,
    tipo TEXT NOT NULL,
    detalle TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_eventos ON eventos(tecnico_id, ts);
CREATE TABLE IF NOT EXISTS ordenes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tecnico_id INTEGER,
    tipo TEXT DEFAULT 'Instalación',
    cliente TEXT NOT NULL,
    telefono TEXT DEFAULT '',
    direccion TEXT DEFAULT '',
    notas TEXT DEFAULT '',
    lat REAL,
    lng REAL,
    fecha TEXT,
    estado TEXT DEFAULT 'pendiente',
    creada INTEGER,
    en_camino INTEGER,
    llegada INTEGER,
    terminada INTEGER,
    nota_tecnico TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS ajustes (
    clave TEXT PRIMARY KEY,
    valor TEXT
);
"""


def db():
    if "tec_db" not in g:
        con = sqlite3.connect(DB_PATH, timeout=15)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(ESQUEMA)
        g.tec_db = con
    return g.tec_db


@bp.teardown_app_request
def _cerrar(_exc):
    con = g.pop("tec_db", None)
    if con is not None:
        con.close()


def ajustes():
    a = dict(AJUSTES_DEFECTO)
    for r in db().execute("SELECT clave, valor FROM ajustes"):
        try:
            a[r["clave"]] = json.loads(r["valor"])
        except ValueError:
            pass
    return a


# ----------------------------------------------------------------- utilidades

def ahora():
    return int(datetime.now(timezone.utc).timestamp())


def local(ts):
    return datetime.fromtimestamp(ts, TZ)


def hhmm(ts):
    return local(ts).strftime("%H:%M") if ts else ""


def _min(hora):
    h, m = hora.split(":")
    return int(h) * 60 + int(m)


def en_horario(ts, a=None):
    a = a or ajustes()
    d = local(ts)
    if d.weekday() not in a["dias"]:
        return False
    m = d.hour * 60 + d.minute
    return _min(a["hora_inicio"]) <= m < _min(a["hora_fin"])


def rango_dia(fecha):
    """fecha 'YYYY-MM-DD' (hora de Ecuador) -> (ts_inicio, ts_fin) en UTC."""
    d = datetime.strptime(fecha, "%Y-%m-%d").replace(tzinfo=TZ)
    return int(d.timestamp()), int((d + timedelta(days=1)).timestamp())


def hoy():
    return datetime.now(TZ).strftime("%Y-%m-%d")


def distancia_m(a_lat, a_lng, b_lat, b_lng):
    r = 6371000.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = p2 - p1
    dl = math.radians(b_lng - a_lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def _hash(t):
    return hashlib.sha256(t.encode()).hexdigest()


def _fila(r):
    return dict(r) if r is not None else None


# ----------------------------------------------------------------- análisis

def calcular_paradas(puntos, minutos):
    """Agrupa puntos seguidos que quedan dentro de RADIO_PARADA_M.
    Devuelve las paradas que duran 'minutos' o más."""
    paradas = []
    i, n = 0, len(puntos)
    while i < n:
        lat, lng = puntos[i]["lat"], puntos[i]["lng"]
        suma_lat, suma_lng, k = lat, lng, 1
        j = i + 1
        while j < n:
            c_lat, c_lng = suma_lat / k, suma_lng / k
            if distancia_m(c_lat, c_lng, puntos[j]["lat"], puntos[j]["lng"]) > RADIO_PARADA_M:
                break
            suma_lat += puntos[j]["lat"]
            suma_lng += puntos[j]["lng"]
            k += 1
            j += 1
        desde, hasta = puntos[i]["ts"], puntos[j - 1]["ts"]
        if hasta - desde >= minutos * 60:
            paradas.append({
                "lat": suma_lat / k, "lng": suma_lng / k,
                "desde": desde, "hasta": hasta,
                "minutos": round((hasta - desde) / 60),
                "desde_txt": hhmm(desde), "hasta_txt": hhmm(hasta),
            })
            i = j
        else:
            i += 1
    return paradas


def km_recorridos(puntos):
    total = 0.0
    for a, b in zip(puntos, puntos[1:]):
        d = distancia_m(a["lat"], a["lng"], b["lat"], b["lng"])
        # descartar saltos de GPS imposibles (> 50 m/s ~ 180 km/h)
        if d / max(1, b["ts"] - a["ts"]) < 50:
            total += d
    return round(total / 1000, 1)


def orden_cercana(lat, lng, ordenes):
    mejor, md = None, RADIO_ORDEN_M
    for o in ordenes:
        if o["lat"] is None:
            continue
        d = distancia_m(lat, lng, o["lat"], o["lng"])
        if d <= md:
            mejor, md = o, d
    return mejor


def orden_de_parada(p, ordenes):
    """Orden a la que pertenece una parada: la que el técnico tenía abierta
    (entre "Llegué" y "Terminé") en ese rato, o la que está a pocos metros."""
    for o in ordenes:
        ini = o.get("llegada")
        if ini:
            fin = o.get("terminada") or ahora()
            if ini <= p["hasta"] and fin >= p["desde"]:
                return o
    return orden_cercana(p["lat"], p["lng"], ordenes)


def estado_actual(tec, a, t_ahora):
    """Estado en vivo de un técnico."""
    con = db()
    ini, _ = rango_dia(hoy())
    pts = [dict(r) for r in con.execute(
        "SELECT ts, lat, lng, bateria, cargando, velocidad FROM puntos "
        "WHERE tecnico_id=? AND ts>=? ORDER BY ts", (tec["id"], ini))]
    ult_ev = con.execute(
        "SELECT tipo, ts FROM eventos WHERE tecnico_id=? AND tipo IN "
        "('gps_apagado','gps_encendido','sesion_fin','sesion_inicio') ORDER BY ts DESC LIMIT 1",
        (tec["id"],)).fetchone()
    e = {"id": tec["id"], "nombre": tec["nombre"], "telefono": tec["telefono"],
         "color": tec["color"], "estado": "sin_datos", "texto": "Sin datos hoy",
         "lat": None, "lng": None, "bateria": None, "cargando": False,
         "ultimo": None, "ultimo_txt": "", "parado_min": 0, "km": 0, "orden": None}
    if not pts:
        if not en_horario(t_ahora, a):
            e["estado"], e["texto"] = "fuera", "Fuera de horario"
        return e
    u = pts[-1]
    e.update(lat=u["lat"], lng=u["lng"], bateria=u["bateria"],
             cargando=bool(u["cargando"]), ultimo=u["ts"], ultimo_txt=hhmm(u["ts"]),
             km=km_recorridos(pts))
    # ¿cuánto tiempo lleva quieto en el último lugar?
    k = len(pts) - 1
    while k > 0 and distancia_m(u["lat"], u["lng"], pts[k - 1]["lat"], pts[k - 1]["lng"]) <= RADIO_PARADA_M:
        k -= 1
    quieto = (t_ahora - pts[k]["ts"]) // 60
    e["parado_min"] = int(quieto)
    ords = [dict(r) for r in con.execute(
        "SELECT id, cliente, lat, lng, llegada, terminada FROM ordenes WHERE tecnico_id=? AND fecha=?",
        (tec["id"], hoy()))]
    oc = orden_de_parada({"lat": u["lat"], "lng": u["lng"], "desde": pts[k]["ts"], "hasta": u["ts"]}, ords)
    if oc:
        e["orden"] = oc["cliente"]
    minutos_sin = (t_ahora - u["ts"]) / 60
    if not en_horario(t_ahora, a):
        e["estado"], e["texto"] = "fuera", "Fuera de horario"
    elif ult_ev is not None and ult_ev["tipo"] == "gps_apagado" and ult_ev["ts"] >= u["ts"]:
        e["estado"], e["texto"] = "gps_apagado", "GPS apagado desde las " + hhmm(ult_ev["ts"])
    elif minutos_sin >= SIN_SENAL_MIN:
        e["estado"], e["texto"] = "sin_senal", "Sin señal desde las " + hhmm(u["ts"])
    elif quieto >= a["minutos_parada"]:
        e["estado"] = "parado"
        e["texto"] = "Parado %d min" % quieto + (" · en " + oc["cliente"] if oc else "")
    else:
        e["estado"], e["texto"] = "movimiento", "En movimiento"
    return e


def alertas_del_dia(fecha, a):
    con = db()
    ini, fin = rango_dia(fecha)
    nombres = {r["id"]: r["nombre"] for r in con.execute("SELECT id, nombre FROM tecnicos")}
    out = []
    for r in con.execute("SELECT * FROM eventos WHERE ts>=? AND ts<? ORDER BY ts", (ini, fin)):
        texto = {
            "gps_apagado": "Apagó el GPS",
            "gps_encendido": "Volvió a encender el GPS",
            "bateria_baja": "Batería baja (%s%%)" % (r["detalle"] or "?"),
            "sin_permiso": "Quitó el permiso de ubicación",
            "sesion_fin": "Cerró sesión en la app",
            "sesion_inicio": "Inició sesión en la app",
            "apagado": "El celular se apagó o reinició",
        }.get(r["tipo"], r["tipo"])
        nivel = "alta" if r["tipo"] in ("gps_apagado", "sin_permiso", "sesion_fin") else \
                "media" if r["tipo"] in ("bateria_baja", "apagado") else "info"
        out.append({"ts": r["ts"], "hora": hhmm(r["ts"]), "tecnico": nombres.get(r["tecnico_id"], "?"),
                    "texto": texto, "nivel": nivel})
    # paradas largas fuera de una orden
    for tid, nombre in nombres.items():
        pts = [dict(p) for p in con.execute(
            "SELECT ts, lat, lng FROM puntos WHERE tecnico_id=? AND ts>=? AND ts<? ORDER BY ts",
            (tid, ini, fin))]
        ords = [dict(o) for o in con.execute(
            "SELECT cliente, lat, lng, llegada, terminada FROM ordenes WHERE tecnico_id=? AND fecha=?", (tid, fecha))]
        for p in calcular_paradas(pts, a["minutos_parada"]):
            if not orden_de_parada(p, ords):
                out.append({"ts": p["desde"], "hora": p["desde_txt"], "tecnico": nombre,
                            "texto": "Parado %d min fuera de una orden (%s a %s)" % (
                                p["minutos"], p["desde_txt"], p["hasta_txt"]),
                            "nivel": "media", "lat": p["lat"], "lng": p["lng"]})
    out.sort(key=lambda x: x["ts"], reverse=True)
    return out


# ----------------------------------------------------------------- acceso panel

def admin_ok():
    if _chequeo_admin is not None:
        try:
            return bool(_chequeo_admin())
        except Exception:
            return False
    return session.get("tecnicos_admin") is True


def _datos():
    """Datos de un POST del panel: JSON, o el campo 'datos' de un formulario
    (CONTROL360 exige formularios con su token csrf)."""
    d = request.get_json(silent=True)
    if d is None:
        try:
            d = json.loads(request.form.get("datos") or "{}")
        except ValueError:
            d = {}
    return d


def requiere_admin(f):
    @wraps(f)
    def envoltura(*args, **kw):
        if not admin_ok():
            if request.path.startswith(url_for("tecnicos.panel") + "panel/api"):
                return jsonify(error="Inicie sesión"), 401
            return redirect(_url_login or url_for("tecnicos.entrar"))
        return f(*args, **kw)
    return envoltura


def requiere_tecnico(f):
    @wraps(f)
    def envoltura(*args, **kw):
        if request.method == "OPTIONS":
            return "", 204
        tok = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
        if not tok:
            return jsonify(error="Sin sesión"), 401
        tec = db().execute("SELECT * FROM tecnicos WHERE token_hash=? AND activo=1",
                           (_hash(tok),)).fetchone()
        if tec is None:
            return jsonify(error="Sesión cerrada. Vuelva a entrar."), 401
        g.tecnico = tec
        return f(*args, **kw)
    return envoltura


@bp.after_request
def _cors(resp):
    if request.path.startswith(url_for("tecnicos.panel") + "api/"):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


# ----------------------------------------------------------------- páginas

def _html(nombre, **reemplazos):
    with open(os.path.join(AQUI, nombre), encoding="utf-8") as fh:
        t = fh.read()
    for k, v in reemplazos.items():
        t = t.replace("{{" + k + "}}", v)
    return Response(t, mimetype="text/html")


@bp.route("/entrar", methods=["GET", "POST"])
def entrar():
    error = ""
    if request.method == "POST":
        if secrets.compare_digest(request.form.get("clave", ""), CLAVE_PANEL):
            session["tecnicos_admin"] = True
            session.permanent = True
            return redirect(url_for("tecnicos.panel"))
        error = "Clave incorrecta"
    return _html("entrar.html", EMPRESA=EMPRESA, ERROR=error)


@bp.route("/salir")
def salir():
    session.pop("tecnicos_admin", None)
    return redirect(url_for("tecnicos.entrar"))


@bp.route("/")
@requiere_admin
def panel():
    integrado = _chequeo_admin is not None
    return _html("panel.html", EMPRESA=EMPRESA, APK_URL=APK_URL,
                 CSRF=str(session.get("csrf", "")),
                 SALIR="/" if integrado else "salir",
                 SALIR_TXT="Volver a CONTROL360" if integrado else "Salir")


@bp.route("/app")
def descargar_app():
    return redirect(APK_URL)


# ----------------------------------------------------------------- API del panel

@bp.route("/panel/api/vivo")
@requiere_admin
def api_vivo():
    a = ajustes()
    t = ahora()
    tecs = db().execute("SELECT * FROM tecnicos WHERE activo=1 ORDER BY nombre").fetchall()
    lista = [estado_actual(x, a, t) for x in tecs]
    alertas = [x for x in alertas_del_dia(hoy(), a) if x["nivel"] != "info"][:30]
    return jsonify(tecnicos=lista, alertas=alertas, en_horario=en_horario(t, a),
                   hora=datetime.now(TZ).strftime("%H:%M"), ajustes=a)


@bp.route("/panel/api/recorrido")
@requiere_admin
def api_recorrido():
    a = ajustes()
    tid = int(request.args.get("tecnico", 0))
    fecha = request.args.get("fecha") or hoy()
    ini, fin = rango_dia(fecha)
    con = db()
    pts = [dict(r) for r in con.execute(
        "SELECT ts, lat, lng, bateria, velocidad FROM puntos WHERE tecnico_id=? AND ts>=? AND ts<? ORDER BY ts",
        (tid, ini, fin))]
    ords = [dict(r) for r in con.execute(
        "SELECT * FROM ordenes WHERE tecnico_id=? AND fecha=? ORDER BY id", (tid, fecha))]
    paradas = calcular_paradas(pts, a["minutos_parada"])
    for p in paradas:
        o = orden_de_parada(p, ords)
        p["orden"] = o["cliente"] if o else None
    for o in ords:
        _decorar_orden(o)
    resumen = {
        "km": km_recorridos(pts),
        "inicio": hhmm(pts[0]["ts"]) if pts else "",
        "fin": hhmm(pts[-1]["ts"]) if pts else "",
        "paradas": len(paradas),
        "min_parado": sum(p["minutos"] for p in paradas),
        "min_parado_fuera": sum(p["minutos"] for p in paradas if not p["orden"]),
        "ordenes_hechas": sum(1 for o in ords if o["estado"] == "terminada"),
        "ordenes_total": len(ords),
    }
    linea = [[p["lat"], p["lng"], hhmm(p["ts"])] for p in pts]
    return jsonify(puntos=linea, paradas=paradas, ordenes=ords, resumen=resumen)


@bp.route("/panel/api/alertas")
@requiere_admin
def api_alertas():
    return jsonify(alertas=alertas_del_dia(request.args.get("fecha") or hoy(), ajustes()))


def _decorar_orden(o):
    o["llegada_txt"] = hhmm(o.get("llegada"))
    o["terminada_txt"] = hhmm(o.get("terminada"))
    o["duracion_min"] = round((o["terminada"] - o["llegada"]) / 60) if o.get("llegada") and o.get("terminada") else None
    return o


@bp.route("/panel/api/tecnicos", methods=["GET", "POST"])
@requiere_admin
def api_tecnicos():
    con = db()
    if request.method == "POST":
        d = _datos()
        nombre = (d.get("nombre") or "").strip()
        usuario = (d.get("usuario") or "").strip().lower()
        pin = (d.get("pin") or "").strip()
        if not nombre or not usuario or len(pin) < 4:
            return jsonify(error="Falta nombre, usuario o un PIN de al menos 4 números"), 400
        if con.execute("SELECT 1 FROM tecnicos WHERE usuario=?", (usuario,)).fetchone():
            return jsonify(error="Ese usuario ya existe"), 400
        con.execute("INSERT INTO tecnicos (nombre, usuario, pin_hash, telefono, color, creado) VALUES (?,?,?,?,?,?)",
                    (nombre, usuario, generate_password_hash(pin), d.get("telefono", ""), d.get("color", ""), ahora()))
        con.commit()
    filas = [dict(id=r["id"], nombre=r["nombre"], usuario=r["usuario"], telefono=r["telefono"],
                  color=r["color"], activo=r["activo"])
             for r in con.execute("SELECT * FROM tecnicos ORDER BY activo DESC, nombre")]
    return jsonify(tecnicos=filas)


@bp.route("/panel/api/tecnicos/<int:tid>", methods=["POST"])
@requiere_admin
def api_tecnico_editar(tid):
    con = db()
    d = _datos()
    for campo in ("nombre", "telefono", "color"):
        if campo in d:
            con.execute("UPDATE tecnicos SET %s=? WHERE id=?" % campo, (d[campo], tid))
    if "activo" in d:
        con.execute("UPDATE tecnicos SET activo=?, token_hash=CASE WHEN ?=0 THEN NULL ELSE token_hash END WHERE id=?",
                    (1 if d["activo"] else 0, 1 if d["activo"] else 0, tid))
    if d.get("pin"):
        if len(d["pin"]) < 4:
            return jsonify(error="El PIN debe tener al menos 4 números"), 400
        con.execute("UPDATE tecnicos SET pin_hash=?, token_hash=NULL WHERE id=?",
                    (generate_password_hash(d["pin"]), tid))
    con.commit()
    return jsonify(ok=True)


@bp.route("/panel/api/ordenes", methods=["GET", "POST"])
@requiere_admin
def api_ordenes():
    con = db()
    if request.method == "POST":
        d = _datos()
        if not (d.get("cliente") or "").strip():
            return jsonify(error="Falta el nombre del cliente"), 400
        con.execute(
            "INSERT INTO ordenes (tecnico_id, tipo, cliente, telefono, direccion, notas, lat, lng, fecha, creada) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (d.get("tecnico_id") or None, d.get("tipo") or "Instalación", d["cliente"].strip(),
             d.get("telefono", ""), d.get("direccion", ""), d.get("notas", ""),
             d.get("lat"), d.get("lng"), d.get("fecha") or hoy(), ahora()))
        con.commit()
    fecha = request.args.get("fecha") or hoy()
    nombres = {r["id"]: r["nombre"] for r in con.execute("SELECT id, nombre FROM tecnicos")}
    ords = []
    for r in con.execute("SELECT * FROM ordenes WHERE fecha=? ORDER BY estado='terminada', id", (fecha,)):
        o = _decorar_orden(dict(r))
        o["tecnico"] = nombres.get(o["tecnico_id"], "Sin asignar")
        ords.append(o)
    return jsonify(ordenes=ords)


@bp.route("/panel/api/ordenes/<int:oid>", methods=["POST"])
@requiere_admin
def api_orden_editar(oid):
    con = db()
    d = _datos()
    if d.get("borrar"):
        con.execute("DELETE FROM ordenes WHERE id=?", (oid,))
    else:
        for campo in ("tecnico_id", "tipo", "cliente", "telefono", "direccion", "notas", "lat", "lng", "fecha", "estado"):
            if campo in d:
                con.execute("UPDATE ordenes SET %s=? WHERE id=?" % campo, (d[campo], oid))
    con.commit()
    return jsonify(ok=True)


@bp.route("/panel/api/ajustes", methods=["GET", "POST"])
@requiere_admin
def api_ajustes():
    if request.method == "POST":
        d = _datos()
        con = db()
        for k in AJUSTES_DEFECTO:
            if k in d:
                con.execute("INSERT OR REPLACE INTO ajustes (clave, valor) VALUES (?,?)", (k, json.dumps(d[k])))
        con.commit()
    return jsonify(ajustes())


# ----------------------------------------------------------------- API de la app

def _config_app():
    a = ajustes()
    return {"hora_inicio": a["hora_inicio"], "hora_fin": a["hora_fin"], "dias": a["dias"],
            "intervalo_seg": a["intervalo_seg"], "empresa": EMPRESA}


@bp.route("/api/login", methods=["POST", "OPTIONS"])
def app_login():
    if request.method == "OPTIONS":
        return "", 204
    d = request.get_json(force=True, silent=True) or {}
    usuario = (d.get("usuario") or "").strip().lower()
    tec = db().execute("SELECT * FROM tecnicos WHERE usuario=? AND activo=1", (usuario,)).fetchone()
    if tec is None or not check_password_hash(tec["pin_hash"], (d.get("pin") or "").strip()):
        return jsonify(error="Usuario o PIN incorrecto"), 401
    tok = secrets.token_urlsafe(32)
    con = db()
    con.execute("UPDATE tecnicos SET token_hash=? WHERE id=?", (_hash(tok), tec["id"]))
    con.execute("INSERT INTO eventos (tecnico_id, ts, tipo) VALUES (?,?,?)", (tec["id"], ahora(), "sesion_inicio"))
    con.commit()
    return jsonify(token=tok, nombre=tec["nombre"], config=_config_app())


@bp.route("/api/config", methods=["GET", "OPTIONS"])
@requiere_tecnico
def app_config():
    return jsonify(nombre=g.tecnico["nombre"], config=_config_app())


@bp.route("/api/ubicaciones", methods=["POST", "OPTIONS"])
@requiere_tecnico
def app_ubicaciones():
    """La app manda lotes: {"puntos":[{ts,lat,lng,acc,vel,bat,carga}], "eventos":[{ts,tipo,detalle}]}"""
    d = request.get_json(force=True, silent=True) or {}
    a = ajustes()
    tid = g.tecnico["id"]
    t = ahora()
    con = db()
    guardados = 0
    for p in d.get("puntos", [])[:2000]:
        try:
            ts = int(p["ts"])
            lat, lng = float(p["lat"]), float(p["lng"])
        except (KeyError, TypeError, ValueError):
            continue
        if ts > t + 300 or ts < t - 7 * 86400 or not en_horario(ts, a):
            continue  # fuera de horario no se guarda nada
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            continue
        if p.get("acc") is not None and float(p["acc"]) > 300:
            continue  # ubicación muy imprecisa
        con.execute("INSERT INTO puntos (tecnico_id, ts, lat, lng, precision, velocidad, bateria, cargando) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (tid, ts, lat, lng, p.get("acc"), p.get("vel"), p.get("bat"), 1 if p.get("carga") else 0))
        guardados += 1
    for e in d.get("eventos", [])[:200]:
        try:
            ts = int(e["ts"])
        except (KeyError, TypeError, ValueError):
            continue
        tipo = str(e.get("tipo", ""))[:30]
        if tipo and (en_horario(ts, a) or tipo in ("sesion_fin",)):
            con.execute("INSERT INTO eventos (tecnico_id, ts, tipo, detalle) VALUES (?,?,?,?)",
                        (tid, ts, tipo, str(e.get("detalle", ""))[:100]))
    con.commit()
    return jsonify(ok=True, guardados=guardados, config=_config_app())


@bp.route("/api/salir", methods=["POST", "OPTIONS"])
@requiere_tecnico
def app_salir():
    con = db()
    con.execute("UPDATE tecnicos SET token_hash=NULL WHERE id=?", (g.tecnico["id"],))
    con.execute("INSERT INTO eventos (tecnico_id, ts, tipo) VALUES (?,?,?)", (g.tecnico["id"], ahora(), "sesion_fin"))
    con.commit()
    return jsonify(ok=True)


@bp.route("/api/ordenes", methods=["GET", "OPTIONS"])
@requiere_tecnico
def app_ordenes():
    ords = [_decorar_orden(dict(r)) for r in db().execute(
        "SELECT * FROM ordenes WHERE tecnico_id=? AND (fecha=? OR (fecha<? AND estado!='terminada')) "
        "ORDER BY estado='terminada', fecha, id", (g.tecnico["id"], hoy(), hoy()))]
    return jsonify(ordenes=ords)


@bp.route("/api/ordenes/<int:oid>", methods=["POST", "OPTIONS"])
@requiere_tecnico
def app_orden_estado(oid):
    con = db()
    o = con.execute("SELECT * FROM ordenes WHERE id=? AND tecnico_id=?", (oid, g.tecnico["id"])).fetchone()
    if o is None:
        return jsonify(error="Orden no encontrada"), 404
    d = request.get_json(force=True, silent=True) or {}
    estado = d.get("estado")
    t = ahora()
    if estado == "en_camino":
        con.execute("UPDATE ordenes SET estado='en_camino', en_camino=? WHERE id=?", (t, oid))
    elif estado == "en_sitio":
        con.execute("UPDATE ordenes SET estado='en_sitio', llegada=? WHERE id=?", (t, oid))
        # si la orden no tenía ubicación, se guarda donde está el técnico al llegar
        if o["lat"] is None and d.get("lat") is not None:
            con.execute("UPDATE ordenes SET lat=?, lng=? WHERE id=?", (d["lat"], d["lng"], oid))
    elif estado == "terminada":
        con.execute("UPDATE ordenes SET estado='terminada', terminada=?, llegada=COALESCE(llegada, ?), "
                    "nota_tecnico=? WHERE id=?", (t, t, (d.get("nota") or "")[:500], oid))
    else:
        return jsonify(error="Estado no válido"), 400
    con.commit()
    return jsonify(ok=True)
