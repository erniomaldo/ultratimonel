# Tasks — Dashboard Stability Fixes

## Fase 1 — Logging persistente (`dashboard_server.py`)

- [x] **1.1** Agregar `import socket` al inicio de `dashboard_server.py`
- [x] **1.2** Definir `LOG_DIR` con fallback a `~/.hermes/logs`, crear directorio si no existe
- [x] **1.3** Configurar `logging.basicConfig` con `FileHandler(LOG_FILE)` + `StreamHandler(sys.stderr)`
- [x] **1.4** Agregar `logger.info("Dashboard log file: %s", LOG_FILE)` post-configuración

## Fase 2 — SO_REUSEADDR + exception handling (`dashboard_server.py`)

- [x] **2.1** En `create_server()`, agregar `server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)`
- [x] **2.2** En `run_server()`, envolver `serve_forever()` con try/except KeyboardInterrupt/Exception/finally
- [x] **2.3** Loggear "Shutting down dashboard server (SIGINT)" en KeyboardInterrupt
- [x] **2.4** Loggear crash con `logger.exception()` en Exception general
- [x] **2.5** Loggear "Dashboard server exited" en finally

## Fase 3 — SQLite timeout (`dashboard_server.py`)

- [x] **3.1** Agregar `timeout=5.0` a `sqlite3.connect(DB_PATH)` en `_db()`

## Fase 4 — Logs de subprocess a archivo (`server.py`)

- [x] **4.1** Calcular `log_dir` desde `db_path` o fallback a `~/.hermes/logs`
- [x] **4.2** Crear directorio con `os.makedirs(log_dir, exist_ok=True)`
- [x] **4.3** Abrir `dashboard_stdout.log` y `dashboard_stderr.log` en modo append
- [x] **4.4** Pasar `stdout=log_out, stderr=log_err` a `subprocess.Popen`

## Fase 5 — Puerto fijo + NO null-tear (`server.py`)

- [x] **5.1** Reemplazar `_find_free_port(DASHBOARD_PORT)` por `DASHBOARD_PORT` directo
- [x] **5.2** En block `status`: leer stderr residual antes de cualquier null-tear, retornar `exit_code` + `stderr_tail`
- [x] **5.3** En block `start` (post-wait crash): retornar `hint` apuntando al log file en lugar de stderr inline
