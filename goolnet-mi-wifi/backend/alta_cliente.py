"""
Da de alta un cliente en clients.json.

Uso:
    python alta_cliente.py 0700000000 1234 48575443-HG8145X6-485754430000XXXX

donde:
    0700000000   = usuario con que entra el cliente (cédula o código)
    1234         = PIN inicial
    48575443-... = device_id de SU ONT en GenieACS (OUI-Modelo-Serie).
                   El _id exacto lo ves en la UI de GenieACS cuando la ONU
                   reporta; la Serie es la que ves en GenieACS (16 hex, empieza por 48575443).
"""

import json
import sys
from pathlib import Path

import auth

if len(sys.argv) != 4:
    print(__doc__)
    sys.exit(1)

usuario, pin, device_id = sys.argv[1], sys.argv[2], sys.argv[3]

p = Path(auth.CLIENTS_FILE)
data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
data.pop("_comentario", None)
data[usuario] = auth.build_client_record(pin, device_id)
p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"OK: cliente {usuario} -> {device_id}")
