# Design — Dashboard Stability Fixes

## Technical Approach

### Objective

Eliminar los crashs recurrentes del dashboard y proveer visibilidad operativa (logs + stderr) cuando ocurren, sin cambiar la funcionalidad de las APIs existentes.

### Strategy: Targeted fixes, zero API breakage

Todos los cambios son internos al runtime del servidor. No se modifican endpoints, schemas de respuesta, ni comportamientos observables por el frontend — salvo adición de campos opcionales (`exit_code`, `stderr_tail`, `hint`) que son backwards-compatible.

---

## Architecture Decisions

### AD-1: SO_REUSEADDR para recuperación inmediata tras crash

**Decision:** Configurar `socket.SO_REUSEADDR = 1` en `create_server()` antes del primer bind.

```python
server = HTTPServer((host, port), DashboardHandler)
server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
```

**Rationale:** Tras un kill o crash, el kernel mantiene el socket en `TIME_WAIT` ~60-120s. Sin SO_REUSEADDR, cualquier intento de bind falla con errno 98. Con esta opción, el nuevo proceso puede reutilizar la dirección inmediatamente.

**Trade-off:** SO_REUSEADDR no protege contra colisiones reales (dos procesos corriendo simultáneamente en el mismo puerto). En la práctica esto no ocurre porque `server.py` verifica `_dashboard_proc.poll()` antes de iniciar. La opción es segura en este contexto monocromatico.

---

### AD-2: Logging dual (file + stderr) con ruta configurable

**Decision:** Configurar `logging.basicConfig` con dos handlers: `FileHandler` a archivo persistente y `StreamHandler` a stderr. Ruta base configurable vía `ULTRATIMONEL_LOG_DIR`.

```python
LOG_DIR = Path(os.environ.get(
    "ULTRATIMONEL_LOG_DIR",
    str(Path.home() / ".hermes" / "logs"),
))
LOG_FILE = str(LOG_DIR / "dashboard.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] dashboard: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stderr),
    ],
)
```

**Rationale:** Los logs en stderr eran efímeros (se perdían al morir el proceso). Los logs en archivo persisten entre reinicios y son consultables con `tail -f`. La variable de entorno permite overrides en contenedores o entornos CI.

**Trade-off:** Se crea un archivo adicional en disco. El directorio se crece automáticamente si no existe. No hay rotation de logs (simple por ahora; se puede agregar `RotatingFileHandler` en el futuro).

---

### AD-3: Puerto fijo en lugar de búsqueda dinámica

**Decision:** Usar `DASHBOARD_PORT` (3005) directamente, eliminando `_find_free_port()`.

**Rationale:** SO_REUSEADDR funciona con puertos fijos. Un puerto dinámico cada arranque genera inconsistencia (el status API reporta un puerto que puede cambiar). El dashboard es una herramienta local/operativa; un puerto fijo es predecible y fácil de monitorear.

**Trade-off:** Si el puerto 3005 está ocupado por otro servicio, fallará el bind. Esto es deseable (fail-fast) vs. silenciosamente usar otro puerto y confundir al operador.

---

### AD-4: Subprocess logs a archivo en lugar de PIPEs

**Decision:** En `server.py`, abrir archivos de log (`dashboard_stdout.log`, `dashboard_stderr.log`) y pasarlos como `stdout`/`stderr` a `subprocess.Popen`.

```python
log_out = open(os.path.join(log_dir, "dashboard_stdout.log"), "a")
log_err = open(os.path.join(log_dir, "dashboard_stderr.log"), "a")
_dashboard_proc = subprocess.Popen(
    [python, script, str(_dashboard_port)],
    stdout=log_out,
    stderr=log_err,
    ...
)
```

**Rationale:** Los PIPEs de subprocess son efímeros: cuando el hijo muere, el contenido del pipe se pierde si no se ha leído. Al usar archivos, el stderr persiste en disco y es consultable post-mortem.

**Trade-off:** Los file objects se abren pero nunca se cierran explícitamente (heredados por el proceso hijo). Esto es aceptable para un servicio de larga duración; los descriptores se liberan al terminar el proceso padre. Si se requiere limpieza estricta, se podría usar `os.dup2()` o gestionar los file objects con un context manager.

---

### AD-5: NO null-tear — preservar referencia del proceso para diagnóstico

**Decision:** Al detectar que `_dashboard_proc.poll()` retorna un exit code, leer stderr residual ANTES de establecer `_dashboard_proc = None`, y retornar `exit_code` + `stderr_tail` en la respuesta de status.

```python
ret = _dashboard_proc.poll()
if ret is not None:
    stderr = ""
    try:
        if _dashboard_proc.stderr:
            raw = _dashboard_proc.stderr.read()
            stderr = raw if isinstance(raw, str) else raw.decode(errors="replace")
    except Exception:
        stderr = "(log file: ~/.hermes/logs/dashboard_stderr.log)"
    return json.dumps({
        **_status_dict(False),
        "exit_code": ret,
        "stderr_tail": stderr[-2000:] if stderr else "",
    })
```

**Rationale:** El null-tear (establecer `None` inmediatamente) perdía el acceso al pipe de stderr. Preservando la referencia, podemos leer lo residual y dar feedback al operador. Para los casos donde ya se escribió a archivo (Fix AD-4), el fallback apunta al log file.

**Trade-off:** `_dashboard_proc` permanece no-null hasta que se haga stop explícito, aunque el proceso haya terminado. El polling periódico en status verifica `poll()` cada vez, por lo que el comportamiento funcional es correcto.

---

### AD-6: Timeout de 5s en conexiones SQLite

**Decision:** Agregar `timeout=5.0` a `sqlite3.connect()`.

```python
conn = sqlite3.connect(DB_PATH, timeout=5.0)
```

**Rationale:** Sin timeout, sqlite3 bloquea indefinidamente si otro proceso mantiene un lock write. Un timeout de 5s es razonable para operaciones de lectura y permite recuperación automática.

**Trade-off:** Si la DB está realmente bloqueada (>5s), las requests retornarán 500 en lugar de colgarse. Esto es preferible a un hang infinito del servidor HTTP.

---

### AD-7: Exception handling con shutdown limpio

**Decision:** Envolver `serve_forever()` en try/except/finally para capturar crashs no esperados y loggear el shutdown.

```python
try:
    server.serve_forever()
except KeyboardInterrupt:
    logger.info("Shutting down dashboard server (SIGINT)")
    server.shutdown()
except Exception as exc:
    logger.exception("Dashboard server crashed: %s", exc)
    server.shutdown()
finally:
    logger.info("Dashboard server exited")
```

**Rationale:** Sin este manejo, una excepción no capturada dentro del loop de serve_forever dejaba el proceso colgado sin logging de causa raíz. Ahora se registra el crash y se hace shutdown limpio.

**Trade-off:** `logger.exception()` incluye traceback completo. En producción esto es útil para debugging; en entornos con logs volátiles, considerar reducir a `logger.error()` si el volumen es alto.

---

## Module Dependencies

```
server.py
  ├── subprocess.Popen → dashboard_server.py
  │     ├── logging (FileHandler + StreamHandler)
  │     ├── sqlite3 (timeout=5.0)
  │     └── socket.SO_REUSEADDR
  └── os/pathlib (log dir creation)
```

`dashboard_server.py` es autocontenida: usa solo stdlib. `server.py` orquesta el subprocess y redirige sus logs.
