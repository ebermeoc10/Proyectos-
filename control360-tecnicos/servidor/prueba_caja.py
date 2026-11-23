"""Prueba de cobros, gastos y caja del técnico con un CONTROL360 simulado.
    python prueba_caja.py
"""
import base64, io, os, sqlite3, sys, tempfile
from contextlib import closing

tmp = tempfile.mkdtemp()
os.environ["TECNICOS_DB"] = os.path.join(tmp, "prueba.db")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tecnicos  # noqa: E402
from app_sola import app  # noqa: E402

# CONTROL360 simulado (solo las tablas que usa el módulo)
C360 = os.path.join(tmp, "c360.db")
with closing(sqlite3.connect(C360)) as c:
    c.executescript("""
    CREATE TABLE clients(id INTEGER PRIMARY KEY, company_id, name, document, phone, address);
    CREATE TABLE client_ip_assignments(client_id, company_id, ip);
    CREATE TABLE client_sta_ines_ip_assignments(client_id, company_id, ip);
    CREATE TABLE invoices(id INTEGER PRIMARY KEY, company_id, client_id, amount_cents, due_date);
    CREATE TABLE payments(id INTEGER PRIMARY KEY, company_id, invoice_id, amount_cents, voided_at);
    CREATE TABLE expenses(id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
        description TEXT NOT NULL, amount_cents INTEGER NOT NULL CHECK(amount_cents>0), spent_at TEXT NOT NULL,
        voided_at TEXT, voided_by INTEGER);
    CREATE TABLE audit(user_id, company_id, action, detail, at);
    INSERT INTO clients VALUES(238,1,'ALVARADO RAMIREZ MIGUEL ANGEL','1100846557','0991576583','MACHALA');
    INSERT INTO invoices VALUES(1,1,238,2000,'2026-11-01');
    """)
    c.commit()


def abrir():
    con = sqlite3.connect(C360)
    con.row_factory = sqlite3.Row
    return con


tecnicos.configurar_control360(abrir, 1, usuario_actual=lambda: {"id": 7, "username": "secretaria"})

p = app.test_client()
assert p.post("/tecnicos/entrar", data={"clave": "orange360"}).status_code == 302
tid = p.post("/tecnicos/panel/api/tecnicos", json={"nombre": "Luis", "usuario": "luis", "pin": "1234"}).json["tecnicos"][0]["id"]
a = app.test_client()
H = {"Authorization": "Bearer " + a.post("/tecnicos/api/login", json={"usuario": "luis", "pin": "1234"}).json["token"]}

# búsqueda de clientes con saldo
r = p.get("/tecnicos/panel/api/clientes?q=alvarado").json
assert r["clientes"][0]["saldo"] == 20.0, r

# orden de cobro: exige cliente
assert p.post("/tecnicos/panel/api/ordenes", json={"tipo": "Cobro", "cliente": "X", "tecnico_id": tid}).status_code == 400
assert p.post("/tecnicos/panel/api/ordenes", json={"tipo": "Cobro", "cliente": "MIGUEL", "tecnico_id": tid,
                                                    "cliente_id": 238, "monto": "20"}).status_code == 200
oid = a.get("/tecnicos/api/ordenes", headers=H).json["ordenes"][0]["id"]

# la ficha de "cliente nuevo" de una orden de cobro se ignora
r = a.post("/tecnicos/api/fichas", headers=H, json={"tipo": "nuevo", "nombre": "MIGUEL", "orden_id": oid})
assert r.status_code == 200 and r.json.get("omitida"), r.json
assert p.get("/tecnicos/panel/api/fichas").json["fichas"] == []

# IP o usuario
assert tecnicos._ip_ok(" 10.0.0.5 ") == "10.0.0.5"
assert tecnicos._ip_ok("cliente.pppoe-01") == "cliente.pppoe-01"
try:
    tecnicos._ip_ok("con espacios")
    raise AssertionError("debió fallar")
except ValueError:
    pass

# terminar el cobro: valida forma de pago
assert a.post("/tecnicos/api/ordenes/%d" % oid, headers=H, json={"estado": "terminada", "monto": "20", "metodo": "Bitcoin"}).status_code == 400
assert a.post("/tecnicos/api/ordenes/%d" % oid, headers=H, json={"estado": "terminada", "monto": "20", "metodo": "Efectivo",
                                                                  "nota": "pagó completo"}).status_code == 200
cob = p.get("/tecnicos/panel/api/cobros").json
assert cob["pendientes"] == 1 and cob["cobros"][0]["monto_tecnico"] == 20 and cob["cobros"][0]["metodo_tecnico"] == "Efectivo", cob

# fondo de $10 para gasolina
assert p.post("/tecnicos/panel/api/caja/movimiento", json={"tecnico_id": tid, "tipo": "fondo", "monto": "10"}).status_code == 200
caja = a.get("/tecnicos/api/caja", headers=H).json["caja"]
assert caja["en_mano"] == 30.0, caja

# gasto sin foto -> error; con foto -> por aprobar
assert a.post("/tecnicos/api/gastos", headers=H, json={"tipo": "Gasolina", "monto": "5"}).status_code == 400
from PIL import Image  # noqa: E402
buf = io.BytesIO(); Image.new("RGB", (40, 30), (200, 50, 50)).save(buf, "JPEG")
foto = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
r = a.post("/tecnicos/api/gastos", headers=H, json={"tipo": "Gasolina", "monto": "5,50", "foto": foto, "nota": "Primax"})
assert r.status_code == 200 and r.json["caja"]["gastos_por_aprobar"] == 1 and r.json["caja"]["en_mano"] == 30.0, r.json
pan = p.get("/tecnicos/panel/api/caja").json
gid = pan["gastos"][0]["id"]
assert pan["pendientes"] == 1 and pan["gastos"][0]["tiene_foto"] == 1
assert p.get("/tecnicos/panel/gastos/%d/foto" % gid).mimetype == "image/jpeg"

# aprobar -> baja la caja y pasa a CONTROL360
r = p.post("/tecnicos/panel/api/gastos/%d" % gid, json={"accion": "aprobar"})
assert r.status_code == 200 and not r.json["aviso"], r.json
with closing(abrir()) as c:
    e = c.execute("SELECT * FROM expenses").fetchone()
    assert e["amount_cents"] == 550 and e["user_id"] == 7 and "Luis" in e["description"] and "Primax" in e["description"], dict(e)
assert p.post("/tecnicos/panel/api/gastos/%d" % gid, json={"accion": "aprobar"}).status_code == 400   # no dos veces
caja = a.get("/tecnicos/api/caja", headers=H).json["caja"]
assert caja["en_mano"] == 24.5 and caja["gastos_por_aprobar"] == 0, caja

# gasto rechazado no cuenta
a.post("/tecnicos/api/gastos", headers=H, json={"tipo": "Otro", "monto": "3", "foto": foto})
gid2 = p.get("/tecnicos/panel/api/caja").json["gastos"][0]["id"]
assert p.post("/tecnicos/panel/api/gastos/%d" % gid2, json={"accion": "rechazar", "nota": "sin factura válida"}).status_code == 200
assert a.get("/tecnicos/api/caja", headers=H).json["caja"]["en_mano"] == 24.5

# entrega a la oficina
r = p.post("/tecnicos/panel/api/caja/movimiento", json={"tecnico_id": tid, "tipo": "entrega", "monto": "24.50", "nota": "cierre"})
assert r.json["caja"]["en_mano"] == 0, r.json
movs = p.get("/tecnicos/panel/api/caja?tecnico_id=%d" % tid).json["movimientos"]
assert [m["clase"] for m in movs].count("gasto") == 2 and any(m["clase"] == "cobro" and m["monto"] == 20 for m in movs), movs
res = p.get("/tecnicos/panel/api/caja").json["resumen"][0]
assert res["nombre"] == "Luis" and res["en_mano"] == 0

# confirmar el cobro con lo que reportó el técnico -> enlace al abono
cid_cobro = cob["cobros"][0]["id"]
r = p.post("/tecnicos/panel/api/cobros/%d" % cid_cobro, json={"accion": "confirmar", "monto": "20", "metodo": "Efectivo"})
assert r.status_code == 200 and r.json["url"] == "/company/1/clients/238/debt?amount=20.00&method=Efectivo", r.json
# al confirmar, el cobro sigue contando una sola vez en la caja
assert a.get("/tecnicos/api/caja", headers=H).json["caja"]["en_mano"] == 0
print("CAJA OK")
