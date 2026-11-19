"""Prueba automática con un técnico simulado en Machala.
    python prueba.py
"""
import os, sys, tempfile, time
from datetime import datetime, timedelta

os.environ["TECNICOS_DB"] = os.path.join(tempfile.mkdtemp(), "prueba.db")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tecnicos  # noqa: E402
from app_sola import app  # noqa: E402

c = app.test_client()
assert c.get("/tecnicos/").status_code == 302                     # pide clave
assert c.post("/tecnicos/entrar", data={"clave": "orange360"}).status_code == 302
assert c.get("/tecnicos/").status_code == 200

r = c.post("/tecnicos/panel/api/tecnicos", json={"nombre": "Luis Pérez", "usuario": "luis", "pin": "1234"})
assert r.status_code == 200, r.json
tid = r.json["tecnicos"][0]["id"]

# login de la app
a = app.test_client()
assert a.post("/tecnicos/api/login", json={"usuario": "luis", "pin": "0000"}).status_code == 401
r = a.post("/tecnicos/api/login", json={"usuario": "luis", "pin": "1234"})
tok = r.json["token"]
H = {"Authorization": "Bearer " + tok}

# día simulado: hoy a las 9:00 (hora Ecuador)
hoy = tecnicos.hoy()
base, _ = tecnicos.rango_dia(hoy)
t0 = base + 9 * 3600
pts = []
lat, lng = -3.2581, -79.9554
# 20 min manejando (moviendo ~200 m cada minuto)
for i in range(20):
    pts.append({"ts": t0 + i * 60, "lat": lat + i * 0.0018, "lng": lng, "acc": 10, "bat": 90 - i // 4})
# 40 min parado en casa del cliente
plat = lat + 20 * 0.0018
for i in range(40):
    pts.append({"ts": t0 + (20 + i) * 60, "lat": plat + (i % 3) * 0.00005, "lng": lng, "acc": 12, "bat": 80})
# 10 min manejando y 20 min parado en otro lado (fuera de orden)
for i in range(10):
    pts.append({"ts": t0 + (60 + i) * 60, "lat": plat, "lng": lng + i * 0.0018, "acc": 10, "bat": 75})
for i in range(20):
    pts.append({"ts": t0 + (70 + i) * 60, "lat": plat, "lng": lng + 10 * 0.0018, "acc": 10, "bat": 12})
# un punto a las 20:00 (fuera de horario, no se debe guardar)
pts.append({"ts": base + 20 * 3600, "lat": lat, "lng": lng, "acc": 10, "bat": 50})
ev = [{"ts": t0 + 85 * 60, "tipo": "bateria_baja", "detalle": "12"},
      {"ts": t0 + 88 * 60, "tipo": "gps_apagado"}]

r = a.post("/tecnicos/api/ubicaciones", json={"puntos": pts, "eventos": ev}, headers=H)
assert r.status_code == 200, r.json
assert r.json["guardados"] == 90, r.json

# orden con ubicación en la casa del cliente
r = c.post("/tecnicos/panel/api/ordenes", json={"cliente": "María Torres", "tipo": "Instalación",
                                                 "tecnico_id": tid, "lat": plat, "lng": lng, "fecha": hoy})
oid = r.json["ordenes"][0]["id"]
assert a.get("/tecnicos/api/ordenes", headers=H).json["ordenes"][0]["cliente"] == "María Torres"
assert a.post(f"/tecnicos/api/ordenes/{oid}", json={"estado": "en_sitio"}, headers=H).status_code == 200
assert a.post(f"/tecnicos/api/ordenes/{oid}", json={"estado": "terminada", "nota": "ok"}, headers=H).status_code == 200

rec = c.get(f"/tecnicos/panel/api/recorrido?tecnico={tid}&fecha={hoy}").json
print("Resumen:", rec["resumen"])
print("Paradas:", [(p["desde_txt"], p["hasta_txt"], p["minutos"], p["orden"]) for p in rec["paradas"]])
assert len(rec["paradas"]) == 2
assert rec["paradas"][0]["orden"] == "María Torres" and rec["paradas"][1]["orden"] is None
assert rec["resumen"]["ordenes_hechas"] == 1

al = c.get(f"/tecnicos/panel/api/alertas?fecha={hoy}").json["alertas"]
print("Alertas:", [(x["hora"], x["texto"]) for x in al])
assert any("GPS" in x["texto"] for x in al) and any("fuera de una orden" in x["texto"] for x in al)

v = c.get("/tecnicos/panel/api/vivo").json
print("En vivo:", [(t["nombre"], t["estado"], t["texto"], t["bateria"]) for t in v["tecnicos"]])

# ajustes
c.post("/tecnicos/panel/api/ajustes", json={"hora_fin": "18:30", "minutos_parada": 15})
assert a.get("/tecnicos/api/config", headers=H).json["config"]["hora_fin"] == "18:30"

# desactivar técnico corta su sesión
c.post(f"/tecnicos/panel/api/tecnicos/{tid}", json={"activo": 0})
assert a.get("/tecnicos/api/config", headers=H).status_code == 401
print("\nTODO OK")
