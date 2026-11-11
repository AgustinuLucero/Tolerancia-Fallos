import subprocess
import sys
import time
import os
import sqlite3
import threading
import uuid
import cliente

os.makedirs("logs", exist_ok=True)

def registrar_tabla(db, titulo, log_file):
    con = sqlite3.connect(db)
    log_file.write(f"\n=== {titulo} ===\nSELECT id, producto, cantidad, clave FROM pedidos;\n")
    try:
        rows = con.execute("SELECT id, producto, cantidad, clave FROM pedidos").fetchall()
        for r in rows:
            log_file.write(f"{r}\n")
        log_file.write(f"Total de filas en pedidos: {len(rows)}\n")
    except sqlite3.OperationalError:
        log_file.write("Tabla 'pedidos' aun no disponible.\n")

    try:
        ops = con.execute("SELECT clave, resultado FROM operaciones").fetchall()
        log_file.write("SELECT clave, resultado FROM operaciones;\n")
        for r in ops:
            log_file.write(f" {r}\n")
    except sqlite3.OperationalError:
        pass
    con.close()

def ejecutar_escenario(modo):
    db = f"pedidos_{modo}.db"
    if os.path.exists(db):
        os.remove(db)
    
    log_path = f"logs/log_{modo}_idempotencia.txt"
    logf = open(log_path, "w", encoding="utf-8")

    # iniciar servidor en subproceso
    srv = subprocess.Popen([sys.executable, "server.py", modo], stdout=logf, stderr=logf)
    time.sleep(1)

    try:
        # redirigir salidas del cliente hacia el mismo archivo de log
        sys.stdout = logf
        registrar_tabla(db, f"ANTES ({modo}) idempotencia", logf)

        # solicitud estandar con timeout y reintentos
        clave = str(uuid.uuid4()) if modo == "con" else None
        cliente.enviar_pedido({"producto": "Notebook", "cantidad": 1}, clave)

        # pruebas adicionales en modo idempotente
        if modo == "con":
            cliente.log("\n--- Prueba: misma clave con contenido DISTINTO ---")
            cliente.enviar_pedido({"producto": "Notebook", "cantidad": 99}, clave, intentos=1)

            cliente.log("\n--- Prueba: 5 solicitudes SIMULTANEAS (concurrencia) ---")

            k2 = "clave-concurrente-1"

            hilos = [
                threading.Thread(
                    target=cliente.enviar_pedido,
                    args=({"producto": "Mouse", "cantidad": 2}, k2, 1, 8)
                ) for _ in range(5)
            ]

            for t in hilos:
                t.start()
            for t in hilos:
                t.join()
        
        time.sleep(6) # esperar a que expiren los timeouts y sleeps
        registrar_tabla(db, f"DESPUES ({modo} idempotencia)", logf)
    finally:
        sys.stdout = sys.__stdout__
        srv.terminate()
        try:
            srv.wait(timeout=3)
        except subprocess.TimeoutExpired:
            srv.kill()
        logf.close()
        time.sleep(1)

if __name__ == "__main__":
    for modo in ("sin", "con"):
        print(f"Ejecutando escenario: {modo} idempotencia...")
        ejecutar_escenario(modo)
    print("\n Ejecucion finalizada con exito!!!!!!")


