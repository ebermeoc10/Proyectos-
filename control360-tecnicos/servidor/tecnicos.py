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


_c360 = {}  # conexión opcional con la base de CONTROL360 (clientes)


def configurar_control360(db, empresa_id, usuario_actual=None, ahora_txt=None):
    """Conecta el módulo con los clientes de CONTROL360.
    db: función que abre la base de CONTROL360; empresa_id: id de Orange.Net."""
    _c360.update(db=db, empresa=empresa_id, usuario=usuario_actual, ahora=ahora_txt)


# ----------------------------------------------------------------- base de datos

METODOS_PAGO = ("Efectivo", "Transferencia", "Depósito")
TIPOS_GASTO = ("Gasolina", "Materiales", "Alimentación", "Transporte", "Otro")

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
CREATE TABLE IF NOT EXISTS gastos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tecnico_id INTEGER NOT NULL,
    tipo TEXT NOT NULL,
    monto REAL NOT NULL,
    nota TEXT DEFAULT '',
    foto BLOB,
    lat REAL,
    lng REAL,
    creada INTEGER,
    estado TEXT DEFAULT 'por_aprobar',
    revisada INTEGER,
    nota_oficina TEXT DEFAULT '',
    gasto_c360 INTEGER
);
CREATE INDEX IF NOT EXISTS ix_gastos ON gastos(tecnico_id, estado);
CREATE TABLE IF NOT EXISTS caja_movs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tecnico_id INTEGER NOT NULL,
    tipo TEXT NOT NULL,            -- 'fondo' (la oficina le da) o 'entrega' (el técnico devuelve)
    monto REAL NOT NULL,
    nota TEXT DEFAULT '',
    creada INTEGER,
    usuario TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS cobros (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    orden_id INTEGER,
    tecnico_id INTEGER,
    cliente_id INTEGER,
    cliente TEXT DEFAULT '',
    monto REAL,
    nota_tecnico TEXT DEFAULT '',
    estado TEXT DEFAULT 'por_confirmar',
    creada INTEGER,
    revisada INTEGER,
    metodo TEXT DEFAULT '',
    monto_recibido REAL,
    nota_oficina TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS fichas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tecnico_id INTEGER NOT NULL,
    tipo TEXT NOT NULL,            -- 'nuevo' o 'actualizar'
    cliente_id INTEGER,            -- cliente de CONTROL360 (al actualizar o al aprobar)
    orden_id INTEGER,
    nombre TEXT DEFAULT '',
    cedula TEXT DEFAULT '',
    telefono TEXT DEFAULT '',
    direccion TEXT DEFAULT '',
    ip TEXT DEFAULT '',
    lat REAL,
    lng REAL,
    foto BLOB,
    notas TEXT DEFAULT '',
    antes TEXT DEFAULT '',         -- datos del cliente antes del cambio (JSON)
    estado TEXT DEFAULT 'pendiente',
    creada INTEGER,
    revisada INTEGER,
    nota_oficina TEXT DEFAULT ''
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
        cols = {r[1] for r in con.execute("PRAGMA table_info(fichas)")}
        for col in ("red", "red_nombre", "usuario_ext"):
            if col not in cols:
                con.execute("ALTER TABLE fichas ADD COLUMN %s TEXT DEFAULT ''" % col)
        cols = {r[1] for r in con.execute("PRAGMA table_info(ordenes)")}
        if "cliente_id" not in cols:
            con.execute("ALTER TABLE ordenes ADD COLUMN cliente_id INTEGER")
        if "monto" not in cols:
            con.execute("ALTER TABLE ordenes ADD COLUMN monto REAL")
        cols = {r[1] for r in con.execute("PRAGMA table_info(cobros)")}
        if "monto_tecnico" not in cols:
            con.execute("ALTER TABLE cobros ADD COLUMN monto_tecnico REAL")
        if "metodo_tecnico" not in cols:
            con.execute("ALTER TABLE cobros ADD COLUMN metodo_tecnico TEXT DEFAULT ''")
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
        cobro_cli = None
        monto = None
        if (d.get("tipo") or "") == "Cobro":
            try:
                cobro_cli = int(d.get("cliente_id"))
            except (TypeError, ValueError):
                return jsonify(error="Para una orden de cobro, busque y elija el cliente de CONTROL360"), 400
            txt = str(d.get("monto") or "").strip().replace(",", ".")
            try:
                monto = round(float(txt), 2) if txt else None
            except ValueError:
                return jsonify(error="El valor a cobrar no es válido"), 400
        con.execute(
            "INSERT INTO ordenes (tecnico_id, tipo, cliente, telefono, direccion, notas, lat, lng, fecha, creada, "
            "cliente_id, monto) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (d.get("tecnico_id") or None, d.get("tipo") or "Instalación", d["cliente"].strip(),
             d.get("telefono", ""), d.get("direccion", ""), d.get("notas", ""),
             d.get("lat"), d.get("lng"), d.get("fecha") or hoy(), ahora(), cobro_cli, monto))
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
        for campo in ("tecnico_id", "tipo", "cliente", "telefono", "direccion", "notas", "lat", "lng", "fecha", "estado", "cliente_id", "monto"):
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
        cobro_monto, cobro_metodo = None, ""
        if (o["tipo"] or "") == "Cobro" and (d.get("monto") not in (None, "") or d.get("metodo")):
            try:
                cobro_monto = round(float(str(d.get("monto")).replace(",", ".")), 2)
            except (TypeError, ValueError):
                cobro_monto = -1
            if cobro_monto < 0:
                return jsonify(error="Escriba el valor que cobró (0 si no pagó)"), 400
            cobro_metodo = d.get("metodo") or ""
            if cobro_metodo not in METODOS_PAGO:
                return jsonify(error="Elija la forma de pago"), 400
        con.execute("UPDATE ordenes SET estado='terminada', terminada=?, llegada=COALESCE(llegada, ?), "
                    "nota_tecnico=? WHERE id=?", (t, t, (d.get("nota") or "")[:500], oid))
        # Orden de cobro terminada: el pago queda "por confirmar" hasta que la oficina lo apruebe.
        if (o["tipo"] or "") == "Cobro" and not con.execute(
                "SELECT 1 FROM cobros WHERE orden_id=?", (oid,)).fetchone():
            con.execute(
                "INSERT INTO cobros (orden_id, tecnico_id, cliente_id, cliente, monto, nota_tecnico, creada, "
                "monto_tecnico, metodo_tecnico) VALUES (?,?,?,?,?,?,?,?,?)",
                (oid, g.tecnico["id"], o["cliente_id"], o["cliente"], o["monto"],
                 (d.get("nota") or "")[:500], t, cobro_monto, cobro_metodo))
    else:
        return jsonify(error="Estado no válido"), 400
    con.commit()
    return jsonify(ok=True)


# ----------------------------------------------------------------- fichas de clientes
#
# El técnico llena una ficha (cliente nuevo o cambios de uno existente) desde la app.
# La oficina la revisa en el panel: los cambios se aplican con un botón; el cliente
# nuevo se crea con el formulario normal de CONTROL360 (que reserva la IP en el
# MikroTik y arma el cobro), y luego se le pega la foto y la ubicación de la casa.

import base64
import ipaddress
from contextlib import closing
from io import BytesIO

CAMPOS_FICHA = ("nombre", "cedula", "telefono", "direccion", "ip", "notas", "red_nombre", "usuario_ext")
REDES = ("orange", "sta_ines", "external")


def _foto_jpeg(b64):
    """Valida y achica la foto (base64) a JPEG de máximo 1600 px."""
    if not b64:
        return None
    if "," in b64[:100]:
        b64 = b64.split(",", 1)[1]
    try:
        crudo = base64.b64decode(b64, validate=False)
    except ValueError:
        raise ValueError("La foto llegó dañada.")
    if len(crudo) > 8 * 1024 * 1024:
        raise ValueError("La foto pesa más de 8 MB.")
    try:
        from PIL import Image, ImageOps
        with Image.open(BytesIO(crudo)) as im:
            if im.format not in ("JPEG", "PNG", "WEBP"):
                raise ValueError("Use una foto JPG o PNG.")
            im = ImageOps.exif_transpose(im)
            im.thumbnail((1600, 1600))
            out = BytesIO()
            im.convert("RGB").save(out, "JPEG", quality=85)
            return out.getvalue()
    except ImportError:
        if crudo[:3] != b"\xff\xd8\xff":
            raise ValueError("Use una foto JPG.")
        return crudo
    except ValueError:
        raise
    except Exception:
        raise ValueError("No se pudo leer la foto.")


def _ip_ok(ip):
    ip = (ip or "").strip()
    if not ip:
        return ""
    try:
        return str(ipaddress.IPv4Address(ip))
    except ValueError:
        pass
    import re as _re
    if _re.fullmatch(r"[A-Za-z0-9._@\-]{2,64}", ip):
        return ip  # usuario (PPPoE u otra red) en vez de IP
    raise ValueError("Escriba una IP (ejemplo: 10.20.30.40) o un usuario (letras, números, . _ - @).")


def _c360_db():
    if not _c360.get("db"):
        raise RuntimeError("El módulo no está conectado con los clientes de CONTROL360.")
    return closing(_c360["db"]())


def _cliente_c360(c, cliente_id):
    emp = _c360["empresa"]
    r = c.execute("SELECT id, name, document, phone, address FROM clients WHERE id=? AND company_id=?",
                  (cliente_id, emp)).fetchone()
    if r is None:
        return None
    d = {"id": r["id"], "nombre": r["name"], "cedula": r["document"] or "",
         "telefono": r["phone"] or "", "direccion": r["address"] or "", "ip": ""}
    try:
        ip = c.execute("SELECT ip FROM client_ip_assignments WHERE client_id=? AND company_id=? "
                       "UNION ALL SELECT ip FROM client_sta_ines_ip_assignments WHERE client_id=? AND company_id=?",
                       (cliente_id, emp, cliente_id, emp)).fetchone()
        if ip:
            d["ip"] = ip[0]
    except sqlite3.Error:
        pass
    return d


def _ficha_dict(r, con_foto=False):
    d = {k: r[k] for k in r.keys() if k != "foto"}
    d["tiene_foto"] = r["foto"] is not None
    d["creada_txt"] = local(r["creada"]).strftime("%d/%m %H:%M") if r["creada"] else ""
    try:
        d["antes"] = json.loads(r["antes"]) if r["antes"] else None
    except ValueError:
        d["antes"] = None
    return d


@bp.route("/api/clientes", methods=["GET", "OPTIONS"])
@requiere_tecnico
def app_buscar_clientes():
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify(clientes=[])
    try:
        with _c360_db() as c:
            filas = c.execute(
                "SELECT id FROM clients WHERE company_id=? AND (name LIKE ? OR phone LIKE ? OR document LIKE ?) "
                "ORDER BY name LIMIT 20", (_c360["empresa"], "%" + q + "%", "%" + q + "%", "%" + q + "%")).fetchall()
            return jsonify(clientes=[_cliente_c360(c, f["id"]) for f in filas])
    except RuntimeError as e:
        return jsonify(error=str(e)), 503


@bp.route("/api/fichas", methods=["GET", "POST", "OPTIONS"])
@requiere_tecnico
def app_fichas():
    con = db()
    tid = g.tecnico["id"]
    if request.method == "POST":
        d = request.get_json(force=True, silent=True) or {}
        tipo = d.get("tipo")
        if tipo not in ("nuevo", "actualizar"):
            return jsonify(error="Tipo de ficha no válido"), 400
        if tipo == "nuevo" and d.get("orden_id"):
            ordn = con.execute("SELECT tipo FROM ordenes WHERE id=?", (d.get("orden_id"),)).fetchone()
            if ordn is not None and (ordn["tipo"] or "Instalación") != "Instalación":
                # Solo las órdenes de instalación crean clientes nuevos; las demás no generan ficha.
                filas = con.execute("SELECT * FROM fichas WHERE tecnico_id=? ORDER BY id DESC LIMIT 20",
                                    (tid,)).fetchall()
                return jsonify(fichas=[_ficha_dict(r) for r in filas], omitida=True)
        datos = {k: str(d.get(k) or "").strip()[:300] for k in CAMPOS_FICHA}
        try:
            datos["ip"] = _ip_ok(datos["ip"])
            foto = _foto_jpeg(d.get("foto") or "")
        except ValueError as e:
            return jsonify(error=str(e)), 400
        red = d.get("red") or "orange"
        if red not in REDES:
            return jsonify(error="Red no válida"), 400
        if red == "external" and tipo == "nuevo":
            if not datos["red_nombre"]:
                return jsonify(error="Escriba el nombre de la otra red"), 400
            if not datos["usuario_ext"] and not datos["ip"]:
                return jsonify(error="Ponga el usuario o la IP de la otra red"), 400
        if red != "external":
            datos["red_nombre"] = datos["usuario_ext"] = ""
        antes = ""
        cliente_id = None
        if tipo == "nuevo" and not datos["nombre"]:
            return jsonify(error="Escriba el nombre del cliente"), 400
        if tipo == "actualizar":
            try:
                cliente_id = int(d.get("cliente_id"))
                with _c360_db() as c:
                    previo = _cliente_c360(c, cliente_id)
            except (TypeError, ValueError):
                return jsonify(error="Elija el cliente"), 400
            except RuntimeError as e:
                return jsonify(error=str(e)), 503
            if previo is None:
                return jsonify(error="Cliente no encontrado"), 404
            antes = json.dumps(previo, ensure_ascii=False)
        lat, lng = d.get("lat"), d.get("lng")
        try:
            lat = float(lat) if lat not in (None, "") else None
            lng = float(lng) if lng not in (None, "") else None
        except (TypeError, ValueError):
            lat = lng = None
        con.execute(
            "INSERT INTO fichas (tecnico_id, tipo, cliente_id, orden_id, nombre, cedula, telefono, direccion, ip, "
            "lat, lng, foto, notas, antes, creada, red, red_nombre, usuario_ext) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (tid, tipo, cliente_id, d.get("orden_id") or None, datos["nombre"], datos["cedula"], datos["telefono"],
             datos["direccion"], datos["ip"], lat, lng, foto, datos["notas"], antes, ahora(),
             red, datos["red_nombre"], datos["usuario_ext"]))
        con.commit()
    filas = con.execute("SELECT * FROM fichas WHERE tecnico_id=? ORDER BY id DESC LIMIT 20", (tid,)).fetchall()
    return jsonify(fichas=[_ficha_dict(r) for r in filas])


@bp.route("/panel/api/fichas")
@requiere_admin
def api_fichas():
    estado = request.args.get("estado") or "pendiente"
    nombres = {r["id"]: r["nombre"] for r in db().execute("SELECT id, nombre FROM tecnicos")}
    filas = db().execute("SELECT * FROM fichas WHERE estado=? ORDER BY id DESC LIMIT 100", (estado,)).fetchall()
    out = []
    for r in filas:
        d = _ficha_dict(r)
        d["tecnico"] = nombres.get(r["tecnico_id"], "?")
        out.append(d)
    pend = db().execute("SELECT COUNT(*) FROM fichas WHERE estado='pendiente'").fetchone()[0]
    return jsonify(fichas=out, pendientes=pend, conectado=bool(_c360.get("db")),
                   empresa_id=_c360.get("empresa"))


@bp.route("/panel/fichas/<int:fid>/foto")
@requiere_admin
def ficha_foto(fid):
    r = db().execute("SELECT foto FROM fichas WHERE id=?", (fid,)).fetchone()
    if r is None or r["foto"] is None:
        return "", 404
    return Response(r["foto"], mimetype="image/jpeg", headers={"Cache-Control": "private, no-store"})


def _audit(c, accion, detalle):
    try:
        u = _c360["usuario"]() if _c360.get("usuario") else None
        c.execute("INSERT INTO audit(user_id,company_id,action,detail,at) VALUES(?,?,?,?,?)",
                  (u["id"] if u else None, _c360["empresa"], accion, str(detalle)[:400],
                   _c360["ahora"]() if _c360.get("ahora") else datetime.now(TZ).isoformat(timespec="seconds")))
    except sqlite3.Error:
        pass


def _pegar_casa(c, cliente_id, f):
    """Guarda ubicación y foto de la casa en el cliente de CONTROL360."""
    emp = _c360["empresa"]
    cols = {r[1] for r in c.execute("PRAGMA table_info(clients)")}
    if "house_location" in cols and f["lat"] is not None:
        c.execute("UPDATE clients SET house_location=? WHERE id=? AND company_id=?",
                  ("%.7f, %.7f" % (f["lat"], f["lng"]), cliente_id, emp))
    if "house_photo" in cols and f["foto"] is not None:
        c.execute("UPDATE clients SET house_photo=? WHERE id=? AND company_id=?", (f["foto"], cliente_id, emp))


@bp.route("/panel/api/fichas/<int:fid>", methods=["POST"])
@requiere_admin
def api_ficha_accion(fid):
    con = db()
    f = con.execute("SELECT * FROM fichas WHERE id=?", (fid,)).fetchone()
    if f is None:
        return jsonify(error="Ficha no encontrada"), 404
    if f["estado"] != "pendiente":
        return jsonify(error="Esta ficha ya fue revisada"), 400
    d = _datos()
    accion = d.get("accion")
    if accion == "rechazar":
        con.execute("UPDATE fichas SET estado='rechazada', revisada=?, nota_oficina=? WHERE id=?",
                    (ahora(), (d.get("nota") or "")[:300], fid))
        con.commit()
        return jsonify(ok=True)
    try:
        with _c360_db() as c, c:
            if accion == "aplicar" and f["tipo"] == "actualizar":
                emp = _c360["empresa"]
                cambios = []
                for campo, col in (("nombre", "name"), ("cedula", "document"), ("telefono", "phone"),
                                   ("direccion", "address")):
                    v = (d.get(campo) if campo in d else f[campo]) or ""
                    if v.strip():
                        c.execute("UPDATE clients SET %s=? WHERE id=? AND company_id=?" % col,
                                  (v.strip(), f["cliente_id"], emp))
                        cambios.append(campo)
                _pegar_casa(c, f["cliente_id"], f)
                _audit(c, "tecnicos_actualiza_cliente", "%s:%s" % (f["cliente_id"], ",".join(cambios)))
                cliente_id = f["cliente_id"]
            elif accion == "vincular" and f["tipo"] == "nuevo":
                # El cliente ya se creó con el formulario de CONTROL360: buscarlo y pegarle la casa.
                nombre = (d.get("nombre") or f["nombre"]).strip()
                r = c.execute("SELECT id FROM clients WHERE company_id=? AND name=? ORDER BY id DESC LIMIT 1",
                              (_c360["empresa"], nombre)).fetchone()
                if r is None:
                    return jsonify(error="No se encontró el cliente recién creado"), 404
                cliente_id = r["id"]
                _pegar_casa(c, cliente_id, f)
                _audit(c, "tecnicos_ficha_cliente", "%s:ficha %s" % (cliente_id, fid))
            else:
                return jsonify(error="Acción no válida"), 400
    except RuntimeError as e:
        return jsonify(error=str(e)), 503
    con.execute("UPDATE fichas SET estado='aprobada', revisada=?, cliente_id=?, nota_oficina=? WHERE id=?",
                (ahora(), cliente_id, (d.get("nota") or "")[:300], fid))
    con.commit()
    return jsonify(ok=True, cliente_id=cliente_id)


# ----------------------------------------------------------------- cobros de los técnicos
#
# Cuando el técnico termina una orden de "Cobro", el pago queda "por confirmar".
# La oficina lo confirma cuando el dinero llega (efectivo entregado o transferencia vista)
# y en ese momento se abre el registro de abono normal de CONTROL360, ya lleno.

def _saldo_c360(c, cliente_id):
    r = c.execute(
        "SELECT COALESCE(SUM(MAX(0, i.amount_cents - COALESCE((SELECT SUM(p.amount_cents) FROM payments p "
        "WHERE p.invoice_id=i.id AND p.company_id=i.company_id AND p.voided_at IS NULL), 0))), 0) "
        "FROM invoices i WHERE i.company_id=? AND i.client_id=?", (_c360["empresa"], cliente_id)).fetchone()
    return round((r[0] or 0) / 100.0, 2)


def _url_pago(cliente_id, monto, metodo):
    from urllib.parse import urlencode
    return "/company/%d/clients/%d/debt?%s" % (
        int(_c360["empresa"]), int(cliente_id), urlencode({"amount": "%.2f" % monto, "method": metodo}))


@bp.route("/panel/api/clientes")
@requiere_admin
def api_buscar_clientes_panel():
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify(clientes=[])
    try:
        with _c360_db() as c:
            filas = c.execute(
                "SELECT id FROM clients WHERE company_id=? AND (name LIKE ? OR phone LIKE ? OR document LIKE ?) "
                "ORDER BY name LIMIT 20", (_c360["empresa"], "%" + q + "%", "%" + q + "%", "%" + q + "%")).fetchall()
            out = []
            for f in filas:
                cli = _cliente_c360(c, f["id"])
                if cli is None:
                    continue
                try:
                    cli["saldo"] = _saldo_c360(c, f["id"])
                except sqlite3.Error:
                    cli["saldo"] = None
                out.append(cli)
            return jsonify(clientes=out)
    except RuntimeError as e:
        return jsonify(error=str(e)), 503


@bp.route("/panel/api/cobros")
@requiere_admin
def api_cobros():
    estado = request.args.get("estado") or "por_confirmar"
    if estado not in ("por_confirmar", "confirmado", "rechazado"):
        estado = "por_confirmar"
    con = db()
    nombres = {r["id"]: r["nombre"] for r in con.execute("SELECT id, nombre FROM tecnicos")}
    filas = [dict(r) for r in con.execute(
        "SELECT * FROM cobros WHERE estado=? ORDER BY id DESC LIMIT 200", (estado,))]
    saldos = {}
    try:
        with _c360_db() as c:
            for f in filas:
                if f["cliente_id"] and f["cliente_id"] not in saldos:
                    saldos[f["cliente_id"]] = _saldo_c360(c, f["cliente_id"])
    except (RuntimeError, sqlite3.Error):
        pass
    for f in filas:
        f["tecnico"] = nombres.get(f["tecnico_id"], "")
        f["fecha"] = local(f["creada"]).strftime("%d/%m %H:%M") if f["creada"] else ""
        f["saldo"] = saldos.get(f["cliente_id"])
        f["url"] = (_url_pago(f["cliente_id"], f["monto_recibido"], f["metodo"])
                    if estado == "confirmado" and f["cliente_id"] and f["monto_recibido"] else "")
    pend = con.execute("SELECT COUNT(*) FROM cobros WHERE estado='por_confirmar'").fetchone()[0]
    return jsonify(cobros=filas, pendientes=pend)


@bp.route("/panel/api/cobros/<int:cobro_id>", methods=["POST"])
@requiere_admin
def api_cobro_accion(cobro_id):
    con = db()
    f = con.execute("SELECT * FROM cobros WHERE id=?", (cobro_id,)).fetchone()
    if f is None:
        return jsonify(error="Cobro no encontrado"), 404
    if f["estado"] != "por_confirmar":
        return jsonify(error="Este cobro ya fue revisado"), 400
    d = _datos()
    accion = d.get("accion")
    if accion == "rechazar":
        con.execute("UPDATE cobros SET estado='rechazado', revisada=?, nota_oficina=? WHERE id=?",
                    (ahora(), (d.get("nota") or "")[:300], cobro_id))
        con.commit()
        return jsonify(ok=True)
    if accion != "confirmar":
        return jsonify(error="Acción no válida"), 400
    try:
        cliente_id = int(f["cliente_id"] or d.get("cliente_id"))
    except (TypeError, ValueError):
        return jsonify(error="Busque y elija el cliente de CONTROL360"), 400
    metodo = d.get("metodo") or "Efectivo"
    if metodo not in ("Efectivo", "Transferencia", "Depósito"):
        return jsonify(error="Forma de pago no válida"), 400
    try:
        monto = round(float(str(d.get("monto") or "").replace(",", ".")), 2)
    except ValueError:
        monto = 0
    if monto <= 0:
        return jsonify(error="Escriba el valor que se recibió"), 400
    try:
        with _c360_db() as c:
            if _cliente_c360(c, cliente_id) is None:
                return jsonify(error="Cliente no encontrado en CONTROL360"), 404
    except RuntimeError as e:
        return jsonify(error=str(e)), 503
    con.execute("UPDATE cobros SET estado='confirmado', revisada=?, metodo=?, monto_recibido=?, cliente_id=?, "
                "nota_oficina=? WHERE id=?",
                (ahora(), metodo, monto, cliente_id, (d.get("nota") or "")[:300], cobro_id))
    con.commit()
    return jsonify(ok=True, url=_url_pago(cliente_id, monto, metodo))


# ----------------------------------------------------------------- caja de cada técnico
#
# Lo que el técnico tiene en la mano = fondos que le dio la oficina + cobros en efectivo
# - gastos aprobados - lo que ya entregó. Los gastos los manda desde la app con foto de
# la factura; la secretaria los aprueba en el panel y pasan a los gastos de CONTROL360.

_EFECTIVO_COBRO = (
    "CASE WHEN metodo_tecnico='Efectivo' THEN COALESCE(monto_tecnico, 0) "
    "WHEN COALESCE(metodo_tecnico, '')='' AND estado='confirmado' AND metodo='Efectivo' "
    "THEN COALESCE(monto_recibido, 0) ELSE 0 END")


def _caja_resumen(con, tid):
    def suma(sql, *a):
        return round(con.execute(sql, a).fetchone()[0] or 0, 2)
    fondos = suma("SELECT SUM(monto) FROM caja_movs WHERE tecnico_id=? AND tipo='fondo'", tid)
    entregas = suma("SELECT SUM(monto) FROM caja_movs WHERE tecnico_id=? AND tipo='entrega'", tid)
    cobros = suma("SELECT SUM(%s) FROM cobros WHERE tecnico_id=? AND estado!='rechazado'" % _EFECTIVO_COBRO, tid)
    gastos = suma("SELECT SUM(monto) FROM gastos WHERE tecnico_id=? AND estado='aprobado'", tid)
    pend = con.execute("SELECT COUNT(*), COALESCE(SUM(monto), 0) FROM gastos WHERE tecnico_id=? "
                       "AND estado='por_aprobar'", (tid,)).fetchone()
    return {"fondos": fondos, "cobros_efectivo": cobros, "gastos_aprobados": gastos, "entregas": entregas,
            "en_mano": round(fondos + cobros - gastos - entregas, 2),
            "gastos_por_aprobar": pend[0], "gastos_por_aprobar_monto": round(pend[1], 2)}


def _caja_movimientos(con, tid, desde=None, hasta=None, limite=200):
    """Movimientos de la caja de un técnico, del más nuevo al más viejo."""
    desde = desde or 0
    hasta = hasta or 4102444800
    movs = []
    for r in con.execute("SELECT * FROM caja_movs WHERE tecnico_id=? AND creada BETWEEN ? AND ?",
                         (tid, desde, hasta)):
        movs.append({"ts": r["creada"], "clase": r["tipo"], "monto": r["monto"],
                     "detalle": "Fondo entregado por la oficina" if r["tipo"] == "fondo" else "Entregó dinero a la oficina",
                     "nota": r["nota"], "estado": ""})
    for r in con.execute("SELECT id, creada, tipo, monto, nota, estado, nota_oficina FROM gastos "
                         "WHERE tecnico_id=? AND creada BETWEEN ? AND ?", (tid, desde, hasta)):
        movs.append({"ts": r["creada"], "clase": "gasto", "monto": r["monto"], "detalle": "Gasto: " + r["tipo"],
                     "nota": r["nota"], "estado": r["estado"], "gasto_id": r["id"],
                     "nota_oficina": r["nota_oficina"]})
    for r in con.execute("SELECT creada, cliente, estado, %s AS ef, monto_tecnico, metodo_tecnico FROM cobros "
                         "WHERE tecnico_id=? AND creada BETWEEN ? AND ?" % _EFECTIVO_COBRO, (tid, desde, hasta)):
        if r["estado"] == "rechazado":
            continue
        movs.append({"ts": r["creada"], "clase": "cobro", "monto": r["ef"],
                     "detalle": "Cobro: " + (r["cliente"] or ""),
                     "nota": ("%s $%.2f" % (r["metodo_tecnico"], r["monto_tecnico"])
                              if r["metodo_tecnico"] and r["monto_tecnico"] is not None else ""),
                     "estado": r["estado"]})
    movs.sort(key=lambda m: m["ts"] or 0, reverse=True)
    for m in movs:
        m["fecha"] = local(m["ts"]).strftime("%d/%m %H:%M") if m["ts"] else ""
    return movs[:limite]


@bp.route("/api/caja", methods=["GET", "OPTIONS"])
@requiere_tecnico
def app_caja():
    con = db()
    tid = g.tecnico["id"]
    return jsonify(caja=_caja_resumen(con, tid), movimientos=_caja_movimientos(con, tid, limite=15),
                   tipos=list(TIPOS_GASTO))


@bp.route("/api/gastos", methods=["POST", "OPTIONS"])
@requiere_tecnico
def app_gasto():
    d = request.get_json(force=True, silent=True) or {}
    tipo = d.get("tipo") or ""
    if tipo not in TIPOS_GASTO:
        return jsonify(error="Elija el tipo de gasto"), 400
    try:
        monto = round(float(str(d.get("monto") or "").replace(",", ".")), 2)
    except ValueError:
        monto = 0
    if monto <= 0 or monto > 5000:
        return jsonify(error="Escriba el valor del gasto"), 400
    try:
        foto = _foto_jpeg(d.get("foto") or "")
    except ValueError as e:
        return jsonify(error=str(e)), 400
    if not foto:
        return jsonify(error="Tome la foto de la factura o recibo"), 400
    try:
        lat = float(d["lat"]) if d.get("lat") not in (None, "") else None
        lng = float(d["lng"]) if d.get("lng") not in (None, "") else None
    except (TypeError, ValueError):
        lat = lng = None
    con = db()
    con.execute("INSERT INTO gastos (tecnico_id, tipo, monto, nota, foto, lat, lng, creada) VALUES (?,?,?,?,?,?,?,?)",
                (g.tecnico["id"], tipo, monto, str(d.get("nota") or "").strip()[:300], foto, lat, lng, ahora()))
    con.commit()
    return jsonify(ok=True, caja=_caja_resumen(con, g.tecnico["id"]))


def _rango_fechas():
    """desde/hasta (AAAA-MM-DD) del panel a timestamps; por defecto los últimos 30 días."""
    try:
        desde = rango_dia(request.args.get("desde"))[0] if request.args.get("desde") else ahora() - 30 * 86400
        hasta = rango_dia(request.args.get("hasta"))[1] if request.args.get("hasta") else ahora() + 60
    except (TypeError, ValueError):
        desde, hasta = ahora() - 30 * 86400, ahora() + 60
    return desde, hasta


@bp.route("/panel/api/caja")
@requiere_admin
def api_caja():
    con = db()
    tecs = [dict(r) for r in con.execute("SELECT id, nombre, activo FROM tecnicos ORDER BY nombre")]
    resumen = []
    for t in tecs:
        c = _caja_resumen(con, t["id"])
        if t["activo"] or c["en_mano"] or c["gastos_por_aprobar"]:
            c.update(id=t["id"], nombre=t["nombre"])
            resumen.append(c)
    nombres = {t["id"]: t["nombre"] for t in tecs}
    estado = request.args.get("estado_gasto") or "por_aprobar"
    if estado not in ("por_aprobar", "aprobado", "rechazado"):
        estado = "por_aprobar"
    gastos = []
    for r in con.execute("SELECT id, tecnico_id, tipo, monto, nota, creada, estado, nota_oficina, lat, lng, "
                         "foto IS NOT NULL AS tiene_foto FROM gastos WHERE estado=? ORDER BY id DESC LIMIT 100",
                         (estado,)):
        x = dict(r)
        x["tecnico"] = nombres.get(x["tecnico_id"], "")
        x["fecha"] = local(x["creada"]).strftime("%d/%m %H:%M") if x["creada"] else ""
        gastos.append(x)
    movs = []
    try:
        tid = int(request.args.get("tecnico_id") or 0)
    except ValueError:
        tid = 0
    if tid:
        desde, hasta = _rango_fechas()
        movs = _caja_movimientos(con, tid, desde, hasta, limite=500)
    pend = con.execute("SELECT COUNT(*) FROM gastos WHERE estado='por_aprobar'").fetchone()[0]
    return jsonify(resumen=resumen, gastos=gastos, movimientos=movs, pendientes=pend,
                   tipos=list(TIPOS_GASTO))


@bp.route("/panel/gastos/<int:gid>/foto")
@requiere_admin
def gasto_foto(gid):
    r = db().execute("SELECT foto FROM gastos WHERE id=?", (gid,)).fetchone()
    if r is None or r["foto"] is None:
        return "", 404
    return Response(r["foto"], mimetype="image/jpeg", headers={"Cache-Control": "private, no-store"})


def _gasto_a_c360(gasto, nombre_tecnico):
    """Registra el gasto aprobado en los gastos de Orange en CONTROL360. Devuelve el id o None."""
    if not _c360.get("db"):
        return None
    u = _c360["usuario"]() if _c360.get("usuario") else None
    if not u:
        return None
    desc = "Gasto técnico %s: %s" % (nombre_tecnico, gasto["tipo"])
    if gasto["nota"]:
        desc += " - " + gasto["nota"]
    cuando = local(gasto["creada"]).isoformat(timespec="seconds")
    with _c360_db() as c, c:
        cur = c.execute("INSERT INTO expenses(company_id,user_id,description,amount_cents,spent_at) VALUES(?,?,?,?,?)",
                        (_c360["empresa"], u["id"], desc[:300], int(round(gasto["monto"] * 100)), cuando))
        _audit(c, "tecnicos_gasto", "gasto %s -> expense %s" % (gasto["id"], cur.lastrowid))
        return cur.lastrowid


@bp.route("/panel/api/gastos/<int:gid>", methods=["POST"])
@requiere_admin
def api_gasto_accion(gid):
    con = db()
    gasto = con.execute("SELECT * FROM gastos WHERE id=?", (gid,)).fetchone()
    if gasto is None:
        return jsonify(error="Gasto no encontrado"), 404
    if gasto["estado"] != "por_aprobar":
        return jsonify(error="Este gasto ya fue revisado"), 400
    d = _datos()
    accion = d.get("accion")
    nota = (d.get("nota") or "")[:300]
    if accion == "rechazar":
        con.execute("UPDATE gastos SET estado='rechazado', revisada=?, nota_oficina=? WHERE id=?",
                    (ahora(), nota, gid))
        con.commit()
        return jsonify(ok=True)
    if accion != "aprobar":
        return jsonify(error="Acción no válida"), 400
    monto = gasto["monto"]
    if d.get("monto") not in (None, ""):
        try:
            monto = round(float(str(d["monto"]).replace(",", ".")), 2)
        except ValueError:
            monto = 0
        if monto <= 0:
            return jsonify(error="Valor no válido"), 400
    nombre = (con.execute("SELECT nombre FROM tecnicos WHERE id=?", (gasto["tecnico_id"],)).fetchone() or [""])[0]
    g2 = dict(gasto)
    g2["monto"] = monto
    aviso = ""
    try:
        exp_id = _gasto_a_c360(g2, nombre)
    except (RuntimeError, sqlite3.Error):
        exp_id = None
    if exp_id is None and _c360.get("db"):
        aviso = "Aprobado, pero no se pudo pasar a los gastos de CONTROL360."
    con.execute("UPDATE gastos SET estado='aprobado', revisada=?, nota_oficina=?, monto=?, gasto_c360=? WHERE id=?",
                (ahora(), nota, monto, exp_id, gid))
    con.commit()
    return jsonify(ok=True, aviso=aviso)


@bp.route("/panel/api/caja/movimiento", methods=["POST"])
@requiere_admin
def api_caja_mov():
    d = _datos()
    tipo = d.get("tipo")
    if tipo not in ("fondo", "entrega"):
        return jsonify(error="Tipo no válido"), 400
    con = db()
    try:
        tid = int(d.get("tecnico_id"))
    except (TypeError, ValueError):
        return jsonify(error="Elija el técnico"), 400
    if con.execute("SELECT 1 FROM tecnicos WHERE id=?", (tid,)).fetchone() is None:
        return jsonify(error="Técnico no encontrado"), 404
    try:
        monto = round(float(str(d.get("monto") or "").replace(",", ".")), 2)
    except ValueError:
        monto = 0
    if monto <= 0:
        return jsonify(error="Escriba el valor"), 400
    u = _c360["usuario"]() if _c360.get("usuario") else None
    quien = ""
    if u:
        for k in ("username", "name", "id"):
            try:
                quien = str(u[k])
                break
            except (KeyError, IndexError):
                continue
    con.execute("INSERT INTO caja_movs (tecnico_id, tipo, monto, nota, creada, usuario) VALUES (?,?,?,?,?,?)",
                (tid, tipo, monto, (d.get("nota") or "")[:300], ahora(), quien))
    con.commit()
    return jsonify(ok=True, caja=_caja_resumen(con, tid))
