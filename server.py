import sqlite3
import json
import time
import sys
import hashlib
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODO = sys.argv[1] if len(sys.argv) >1 else "sin"
PORT = 8765
DELAY = 5 #para forzar el timeout cliente
DB = f"pedidos_{MODO}.db"

def log(msg):
    print(f"{datetime.now():%H:%M:%S.%f}"[:-3] + f" [SERVER-{MODO}] {msg}", flush=True)

def init_db():
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE  IF NOT EXISTS pedidos(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        producto TEXT,
        cantidad INTEGER,
        fecha TEXT,
        clave TEXT
    );

    CREATE TABLE IF NOT EXISTS operaciones(
        clave TEXT PRIMARY KEY,
        hash TEXT NOT NULL,
        resultado TEXT
    );
    """)
    con.commit()
    con.close()

def crear_sin_idem(body):
    #insertar la solicitud ciegamente
    con = sqlite3.connect(DB)
    cur = con.execute(
        "INSERT INTO pedidos(producto, cantidad, fecha) VALUES(?,?,?)",
        (body["producto"], body["cantidad"], datetime.now().isoformat())
    )
    con.commit()
    pid = cur.lastrowid
    con.close()
    return 201, {"pedido_id": pid, "estado": "creado"}, False

def crear_con_idem(clave,body):
    #idempotencia con transacciones y clave unica

    #calcualr el hash del contenido
    h = hashlib.sha256(json.dumps(body, sort_keys= True).encode()).hexdigest()
    con = sqlite3.connect(DB, timeout=10, isolation_level=None)

    try:
        #bloqueo de escritura para evitar carreras concurrentes
        con.execute("BEGIN IMMEDIATE")

        try:
            # registrar clave unica
            con.execute("INSERT INTO operaciones(clave,hash) VALUES(?,?)", 
            (clave,h))

        except sqlite3.IntegrityError:
            #si la clave existe cancela la insercion
            con.execute("ROLLBACK")
            
            hash_ant, res = con.execute(
                "SELECT hash, resultado FROM operaciones WHERE clave=?", (clave,)
            ).fetchone()
            
            #misma clave reusada y distinto contenido
            if hash_ant != h:
                return 422, {"error": "misma clave con contenido distinto"}, True

            #respuesta almacenada sin duplicaf efectos
            return 200, json.loads(res), True
        
        #clave nueva, se guarda el pedido
        cur = con.execute(
            "INSERT INTO pedidos(producto, cantidad, fecha, clave) VALUES(?,?,?,?)",
            (body["producto"], body["cantidad"], datetime.now().isoformat(), clave)
        )
        resultado = {"pedido_id": cur.lastrowid, "estado":"creado"}

        #actualiza el resultado guardado y confirmacion de transaccion
        con.execute("UPDATE operaciones SET RESULTADO=? WHERE clave = ?", (json.dumps(resultado), clave))
        con.execute("COMMIT")

        return 201, resultado, False
    
    except Exception:
        try:
            con.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        con.close()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass #desactiva logs automaticos para no ensuciar la salida

    def _send(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    
    def do_GET(self):
        con = sqlite3.connect(DB)
        rows = con.execute("SELECT id, producto, cantidad, clave FROM pedidos").fetchall()
        con.close()
        self._send(200, rows)

    def do_POST(self):
        length_header = self.headers.get("Content-Length")
        if length_header is not None:
            length = int(length_header)
            raw_data = self.rfile.read(length) if length > 0 else b""
        else:
            raw_data = b""

        if not raw_data:
            log("Cuerpo vacio recibido")
            return self._send(400, {"error": "cuerpo vacio"})
        
        try:
            body = json.loads(raw_data.decode("utf-8"))
        except Exception as e:
            log(f"Error decodificando JSON: {e}")
            return self._send(400, {"error": f"JSON invalido: {e}"})
        
        clave = self.headers.get("Idempotency-Key")
        log(f"recibida solicitud clave={clave} body={body}")

        if MODO == "con":
            if not clave:
                return self._send(400,{"error": "falta Idempotency-Key"})
            code,resp,repetida = crear_con_idem(clave, body)

        else:
            code,resp,repetida = crear_sin_idem(body)
        
        if repetida:
            log(f"DUPLICADO detectado clave={clave} -> NO se crea pedido, devuelvo {code} {resp}")
            self._send(code, resp)

        else:
            log(f"pedido GUARDADO {resp}. Simulo demora de {DELAY}s antes de responder...")
            time.sleep(DELAY)  # forzar timeout en el cliente

            try:
                self._send(code, resp)
                log(f"respuesta enviada {code}")
            except (BrokenPipeError, ConnectionResetError, OSError):
                log("no pude responder: el cliente ya cerro la conexion")

if __name__ == "__main__":
    init_db()
    log(f"escuchando en: {PORT}")
    ThreadingHTTPServer.allow_reuse_address = True
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
