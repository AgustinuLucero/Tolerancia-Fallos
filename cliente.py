import json
import sys
import time
import uuid
import socket
import http.client
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

URL = "http://127.0.0.1:8765/pedidos"

def log(msg):
    print(f"{datetime.now():%H:%M:%S.%f}"[:-3] + f" [CLIENTE] {msg}", flush=True)

def enviar_pedido(body, clave=None, intentos=3, timeout=2, base=1):
    for n in range(1, intentos + 1):
        headers = {"Content-Type": "application/json"}
        
        if clave:
            headers["Idempotency-Key"] = clave
        
        req = Request(URL, json.dumps(body).encode(), headers, method="POST")
        log(f"intento {n}/{intentos} clave={clave}")

        try:
            with urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
                log(f"RESPUESTA {r.status} {data}")
                return data
        except HTTPError as e:
            # los errores 400s no deben reintentarse
            contenido = e.read().decode()
            log(f"HTTP {e.code} {contenido}")
            return None
        except (URLError, TimeoutError, socket.timeout, http.client.RemoteDisconnected, ConnectionResetError) as e:
            log(f"TIMEOUT/ERROR ({e})")
        
        if n < intentos:
            espera = base * (2 ** (n - 1))
            log(f"espero {espera}s (backoff) y reintento")
            time.sleep(espera)
    
    log("reintentos agotados: el cliente cree que FALLO")
    return None

if __name__ == "__main__":
    modo = sys.argv[1] if len(sys.argv) > 1 else "sin"
    #la calve de idempotencia se genera una sola vez por operacion logica
    clave = str(uuid.uuid4()) if modo == "con" else None
    enviar_pedido({"producto": "Notebook", "cantidad":1}, clave)
