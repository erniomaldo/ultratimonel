# Proposal — Dashboard Stability Fixes

## Problema

El dashboard de Ultratimonel sufría tres tipos de crash que lo hacían poco confiable en producción:

1. **Crash al reiniciar rápidamente**: Tras una caída o kill del proceso, el puerto 3005 permanecía en estado `TIME_WAIT`. El siguiente intento de iniciar el servidor fallaba con `OSError: [Errno 98] Address already in use`, dejando el dashboard fuera de línea hasta que el SO liberaba el puerto (hasta 2 minutos).

2. **Logs efímeros e invisibles**: El stderr del proceso se capturaba en un PIPE de subprocess que se perdía al morir el hijo. Cuando el dashboard crasheaba, no había forma de ver qué pasó — ni en el status API ni en ningún archivo.

3. **Puerto dinámico inestable**: `server.py` usaba `_find_free_port()` para asignar un puerto aleatorio cada vez. Esto generaba inconsistencia (¿qué puerto está corriendo?), conflictos con firewalls, y hacía imposible el SO_REUSEADDR (porque el puerto cambiaba en cada arranque).

4. **Falta de manejo de excepciones**: `run_server()` no capturaba excepciones no esperadas; un crash interno dejaba el proceso colgado sin shutdown limpio ni logging.

## Summary

Fixes orientados a estabilidad operativa, no a funcionalidad nueva:

- **SO_REUSEADDR** en `create_server()` para permitir reocupar el puerto inmediatamente tras caída.
- **Logging persistente** a archivo (`~/.hermes/logs/dashboard.log`) + stderr, configurado antes de cualquier operación.
- **Puerto fijo** (3005) en lugar de búsqueda dinámica — compatible con SO_REUSEADDR.
- **Logs de subprocess a archivos** (`dashboard_stdout.log`, `dashboard_stderr.log`) en lugar de PIPEs efímeros.
- **Manejo de excepciones** en `run_server()` con shutdown limpio y logging de crash.
- **NO null-tear** del `_dashboard_proc` al detectar salida: el proceso se conserva para poder leer stderr residual y reportar exit_code + stderr_tail en status API.

## Definiciones

- **SO_REUSEADDR**: Opción de socket que permite a un proceso reutilizar una dirección local que está en estado `TIME_WAIT`, evitando el error "Address already in use".
- **TIME_WAIT**: Estado TCP post-cierre donde el socket permanece activo por ~60-120s para asegurar que segmentos retrasados no lleguen a un nuevo socket.
- **Null-tear**: Patrón de establecer una referencia a `None` inmediatamente tras detectar que un proceso hijo terminó, perdiendo acceso a su stdout/stderr residual.
- **PIPE efímero**: Buffer de subprocess que se pierde cuando el proceso hijo muere y nadie lee sus streams.

## Proposed Solution

### Fix 1 — SO_REUSEADDR (`dashboard_server.py`)

Agregar `import socket` y configurar `SO_REUSEADDR=1` en el socket antes de bind:

```python
server = HTTPServer((host, port), DashboardHandler)
server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
```

Esto permite que un nuevo proceso pueda bind al mismo puerto inmediatamente tras una caída, sin esperar a que el SO libere el TIME_WAIT.

### Fix 2 — Logging persistente (`dashboard_server.py`)

Configurar logging con `FileHandler` apuntando a `~/.hermes/logs/dashboard.log`, además del stream a stderr:

```python
LOG_DIR = Path(os.environ.get("ULTRATIMONEL_LOG_DIR", str(Path.home() / ".hermes" / "logs")))
LOG_FILE = str(LOG_DIR / "dashboard.log")
logging.basicConfig(
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stderr)],
)
```

El directorio se crea automáticamente si no existe. La ruta es configurable vía variable de entorno `ULTRATIMONEL_LOG_DIR`.

### Fix 3 — Timeout en conexión SQLite (`dashboard_server.py`)

Agregar `timeout=5.0` a `sqlite3.connect()` para evitar bloqueos infinitos si hay otro proceso manteniendo un lock en la DB:

```python
conn = sqlite3.connect(DB_PATH, timeout=5.0)
```

### Fix 4 — Manejo de excepciones en run_server (`dashboard_server.py`)

Agregar captura de `Exception` general y bloque `finally` para logging de salida limpia:

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

### Fix 5 — Logs de subprocess a archivo (`server.py`)

Reemplazar `stdout=subprocess.PIPE, stderr=subprocess.PIPE` por archivos abiertos en modo append:

```python
log_out = open(os.path.join(log_dir, "dashboard_stdout.log"), "a")
log_err = open(os.path.join(log_dir, "dashboard_stderr.log"), "a")
```

### Fix 6 — Puerto fijo + NO null-tear (`server.py`)

- Usar `DASHBOARD_PORT` directamente en lugar de `_find_free_port()`.
- Al detectar que el proceso terminó en status/start-check, leer stderr residual ANTES de null-tear, y retornar `exit_code` + `stderr_tail` (o hint al log file).

### Fix 7 — Hint de debug al crash inmediato (`server.py`)

En lugar de retornar solo el exit code cuando el dashboard crashea en los primeros 500ms, retornar un `hint` apuntando al archivo de log para facilitar debugging.

## Impacto

| Aspecto | Antes | Después |
|---------|-------|---------|
| Reinicio tras crash | Falla con "Address already in use" | Funciona inmediatamente |
| Diagnóstico de crash | Sin logs, sin stderr | Logs en disco + stderr_tail en API |
| Consistencia de puerto | Variable (aleatorio) | Fijo (3005) |
| Bloqueo SQLite | Posible hang infinito | Timeout 5s |
| Manejo de exceptions | Proceso colgado | Shutdown limpio + log |

## Rollback Plan

Todos los cambios son backwards-compatible:
- El logging a archivo es aditivo — no rompe nada existente.
- SO_REUSEADDR es un socket option que no afecta el comportamiento normal.
- Puerto fijo: si algo depende del puerto dinámico, se revierte a `_find_free_port()`.
- Timeout SQLite: valor razonable (5s), reversible a `sqlite3.connect(DB_PATH)`.

## Affected Components

- `ultratimonel/dashboard_server.py` — logging, socket options, exception handling, DB timeout
- `ultratimonel/server.py` — subprocess log redirection, fixed port, NO null-tear status reporting
