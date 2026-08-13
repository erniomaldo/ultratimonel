# Design: Snapshot Workflow Adoption (Card #150)

> **Change:** `snapshot-workflow-adoption` · **Date:** 2026-08-12 · **Capability:** `snapshot-workflow`
> **Inputs:** [proposal.md](./proposal.md) · [spec.md](./specs/snapshot-workflow/spec.md)

---

## 1. Architecture Decision Records

### ADR-1: Snapshot como estado derivado — repo como fuente de verdad

**Contexto:** El otro Hermes usa un workflow de snapshot donde skills/plugins se sincronizan a una ubicación de snapshot (`~/.hermes/skills/` para skills, según README). Los skills `ultratimonel-ciclo-basico` y `protocolo-de-trazabilidad` difieren entre repo y snapshot; `opencode` y `pipeline-determinista-ui-code` faltan. El repo ya estableció (ADR-007, change `plugin-preflight-sync`) que el repo es la única fuente de verdad y la instalación es destino.

**Alternativas consideradas:**
1. Editar directamente la copia del snapshot — causa desync permanente (regla ya rechazada en README y ADR-007).
2. Snapshot como estado derivado del repo — copia SIEMPRE repo → snapshot, nunca al revés.
3. Cargar skills directamente desde el repo sin snapshot — requiere que el runtime soporte paths relativos al proyecto (no adoptado).

**Decisión:** Opción 2. El snapshot es **estado derivado**. Todo lo que el repo posee (skills `ultratimonel-ciclo-basico`, `protocolo-de-trazabilidad`, plugin) se copia desde el repo hacia el snapshot. Los skills que el repo no posee (`opencode`, `pipeline-determinista-ui-code`) se copian desde sus ubicaciones canónicas externas, documentando su origen.

**Consecuencias:**
- Si se detecta desync, el fix es portar del repo AL snapshot, no al revés.
- Los skills faltantes tienen origen externo: el snapshot los incluye pero el repo no los versiona; la fuente se documenta en el README.
- La regla anti-desync se extiende de plugin a skills (README sección "Instalar las skills").

---

### ADR-2: Fix de firma de hooks — sin `ctx` como primer parámetro

**Contexto:** `_gates_bouncer(ctx, tool_name, args)` y `_post_turn_guard(ctx, tool_name, args, result)` declaran `ctx` como primer parámetro. La convención del runtime Hermes adoptada (snapshot corregido del otro Hermes) NO pasa `ctx` a los hooks: cada hook recibe solo sus argumentos específicos (`tool_name`/`args`/`result` para pre/post_tool_call).

**Decisión:** Eliminar `ctx` como primer parámetro:

```python
# ANTES (plugin_preflight.py)
def _gates_bouncer(ctx: Any, tool_name: str, args: dict, **kwargs) -> dict | None:
def _post_turn_guard(ctx: Any, tool_name: str, args: dict, result: dict, **kwargs) -> dict | None:

# DESPUÉS
def _gates_bouncer(tool_name: str, args: dict, **kwargs) -> dict | None:
def _post_turn_guard(tool_name: str, args: dict, result: dict, **kwargs) -> dict | None:
```

`_on_session_start(session_id, **kwargs)` y `_pre_llm_call(session_id, user_message, is_first_turn, **kwargs)` ya cumplen la convención — verificar, no cambiar. Ningún hook usa `ctx` internamente (inspección del cuerpo de las funciones: no hay referencias a `ctx`).

**Consecuencias:**
- Cambio de firma de 2 funciones; comportamiento interno idéntico (NF-SW-01).
- Bump de `plugin.yaml` a 2.0.1 para que el deploy detecte la versión corregida; el log de `register()` pasa de `"Plugin v2.0"` a `"v2.0.1"` (nota cosmética alineada al bump).
- Verificación: inspección de firmas + smoke check de runtime operacionalizado en design §5.2 (paso 2), S8 y T6.

---

### ADR-3: Decisión de versión de `custom-dangerous-patterns` — 0.3.4 vs 1.6.0 (docs-only)

**Contexto:** La dependencia de patrones dangerous está sin pin entre 0.3.4 y 1.6.0 en el runtime del snapshot. **Verificado contra el repo: `custom-dangerous-patterns` NO aparece en ningún manifest del repo** (`requirements.txt` contiene solo `fastmcp`, `httpx`; `pyproject.toml` solo `fastmcp`, `httpx`). El pin vive en el runtime externo del snapshot de Hermes, no en este repo. Por lo tanto, esta decisión se registra en documentación; no hay manifest del repo que pinear.

**Alternativas consideradas:**
1. Pin 0.3.4 (conservadora): menor riesgo de breaking; alinea con "adoptar el snapshot tal cual"; diff mínimo contra el runtime actual.
2. Pin 1.6.0 (actualizada): features/fixes nuevos, pero mayor riesgo de cambio de comportamiento en patrones existentes.
3. No registrar nada (rechazada): deja la decisión implícita e inauditable.

**Decisión:** **0.3.4 por defecto** para la adopción del snapshot (estabilidad primero, diff mínimo). La decisión queda registrada en ADR-3 + README como documentación. Si la verificación post-cambio detecta que el runtime requiere 1.6.0 (patrones faltantes o incompatibilidad), se flipea a 1.6.0 con migración explícita.

**Consecuencias:**
- La decisión queda explicitada en la documentación del snapshot, no implícita (auditable por PR vía ADR-3 + README).
- NO se realiza un pin en manifests del repo — la dependencia no existe ahí (evidencia: `requirements.txt`, `pyproject.toml`).
- Cualquier upgrade futuro a 1.6.0 requiere validación de patrones y diff de comportamiento.
- **OPEN QUESTION (resuelta):** la versión que usa el snapshot del otro Hermes se confirma en apply-time (T5); el default documentado es 0.3.4 hasta nueva evidencia.

---

### ADR-4: Parametrización del cliente MCP — post-estado (YA implementada, sin código nuevo)

**Contexto:** El working tree de `ultratimonel_client.py` YA implementa la resolución del server MCP vía env vars `ULTRATIMONEL_MCP_CMD` / `ULTRATIMONEL_MCP_ARGS`, con fallback a la config MCP activa de Hermes (`_hermes_mcp_config()` leyendo `~/.hermes/config.yaml`, línea ~37) y finalmente a `sys.executable`/portable. También resuelve vars Nextcloud/checkpoint con el mismo patrón. Esta implementación está **sin commitear** (git status: `ultratimonel_client.py` +96/-8, `.env.example` untracked).

**Decisión:** (post-estado) Este cambio NO planea código nuevo. Alinea spec/design/tasks con la implementación existente y documenta el mecanismo. La env var previamente planeada `ULTRATIMONEL_HERMES_HOME` queda **obsoleta** — el mecanismo implementado usa `ULTRATIMONEL_MCP_CMD`/`ULTRATIMONEL_MCP_ARGS`, no un home base.

**Consecuencias:**
- Spec F-SW-07 y tasks T4 se reescriben como requisito de documentación/verificación del estado real, no como implementación.
- `.env.example` (untracked) documenta las vars del mecanismo; decisión de PR: incluirlo o dejarlo fuera (ver Review Workload Forecast en tasks.md).
- Riesgo bajo; el comportamiento actual (fallback portable) preserva compatibilidad.
- **Advertencia (char-split) — nota de documentación, sin propuesta de cambio:** `_resolve_mcp_args()` aplica `list(args)` sobre el valor de config de Hermes; si `ULTRATIMONEL_MCP_ARGS` llega como string desde `~/.hermes/config.yaml`, ese string se trataría como lista de caracteres (char-split). Limitar el formato a env var string o lista explícita. Es código YA implementado que este cambio solo documenta; no se propone modificar el código.

---

## 2. Component Design

### 2.1 Skills sync flow

```
repo: skills/ultratimonel-ciclo-basico/SKILL.md ──► ~/.hermes/skills/ultratimonel-ciclo-basico/
repo: skills/protocolo-de-trazabilidad/SKILL.md ──► ~/.hermes/skills/protocolo-de-trazabilidad/
origen externo: opencode ────────────────────────► ~/.hermes/skills/opencode/
origen externo: pipeline-determinista-ui-code ───► ~/.hermes/skills/pipeline-determinista-ui-code/
```

Regla: `cp -r` repo → snapshot. Diff previo para detectar desync (warn si la copia del snapshot difiere del repo). El snapshot destino de skills es `~/.hermes/skills/` (confirmado en README sección "Instalar las skills del proyecto").

### 2.2 Hook signature changes (`ultratimonel/plugin_preflight.py`)

| Hook | ANTES | DESPUÉS |
|------|-------|---------|
| `pre_tool_call` | `_gates_bouncer(ctx, tool_name, args, **kwargs)` | `_gates_bouncer(tool_name, args, **kwargs)` |
| `post_tool_call` | `_post_turn_guard(ctx, tool_name, args, result, **kwargs)` | `_post_turn_guard(tool_name, args, result, **kwargs)` |
| `on_session_start` | `_on_session_start(session_id, **kwargs)` | sin cambios (verificar) |
| `pre_llm_call` | `_pre_llm_call(session_id, user_message, is_first_turn, **kwargs)` | sin cambios (verificar) |

### 2.3 Client MCP resolution (post-estado — YA implementado en working tree)

Mecanismo real en `ultratimonel_client.py` (sin cambios en este cambio):

```python
# _hermes_mcp_config() (línea ~37) — fallback a config MCP activa de Hermes
cfg_path = Path.home() / ".hermes" / "config.yaml"

# Resolución de cmd/args: env var → config Hermes → portable
ULTRATIMONEL_CMD  = os.environ.get("ULTRATIMONEL_MCP_CMD")  o cfg.get("command") o sys.executable
ULTRATIMONEL_ARGS = os.environ.get("ULTRATIMONEL_MCP_ARGS") o cfg.get("args") o []
```

Este cambio solo documenta este mecanismo (F-SW-07) y verifica que `.env.example` cubre las vars. `ULTRATIMONEL_HERMES_HOME` NO existe y no se agrega (ADR-4).

---

## 3. Data Flow Diagrams

### 3.1 Snapshot sync flow

```
verificación_post_cambio():
    .venv/bin/python -m py_compile plugin_preflight.py + ultratimonel_client.py → OK
    smoke check runtime (.venv/bin/python - <<PY ...)                        → hooks sin ctx + register OK
    diff -r repo/skills ~/.hermes/skills                                      → vacío (skills del repo)
    ls ~/.hermes/skills                                                       → 4 skills presentes
    inspección de firmas (inspect.signature)                                  → sin ctx
    .venv/bin/pytest tests/                                                   → suite existente pasa
```

---

## 4. Risk Matrix

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|------------|--------|------------|
| R1 | Desync recurrente repo/snapshot | Medium | Low | Snapshot siempre derivado del repo; diff antes de copiar; regla documentada en README |
| R2 | Firma sin ctx rompe en runtime que sí pasa ctx | Low | Medium | Alineado con el snapshot corregido del otro Hermes; smoke check de runtime operacionalizado en §5.2 / S8 / T6 |
| R3 | Decisión de `custom-dangerous-patterns` incorrecta para el runtime | Medium | Medium | Decisión docs-only en ADR-3 + README (sin manifest en repo — verificado); validación post-cambio antes de flipear a 1.6.0 |
| R4 | Skills faltantes sin fuente disponible | Low | Medium | Task falla con error claro; snapshot diff detecta ausencia |
| R5 | Cambio de firma altera comportamiento (regresión) | Low | Low | Solo se elimina el parámetro; cuerpo de funciones sin cambios; suite de tests |

---

## 5. Test Impact Analysis

### 5.1 Existing tests

| Test | Change needed? | Reason |
|------|---------------|--------|
| Suite existente (`tests/`) | No | El fix es de firma, no de comportamiento; las tools/gates del server no cambian |

### 5.2 Verification steps (no unit tests — el cambio es a nivel firma/sync)

1. `.venv/bin/python -m py_compile ultratimonel/plugin_preflight.py ultratimonel/ultratimonel_client.py`
2. **Runtime smoke check (operacionalización de ADR-2 y F-SW-05/S5):** `.venv/bin/python` ejecutando un snippet que: (a) importa `ultratimonel.plugin_preflight`, (b) inspecciona `inspect.signature` de los 4 hooks — `_gates_bouncer`/`_post_turn_guard` (sin `ctx`, ADR-2) y `_on_session_start`/`_pre_llm_call` (que tampoco reciban `ctx`, F-SW-05/S5) —, (c) llama a `register(ctx_fake)` con un contexto simple, (d) ejerce `_gates_bouncer('write_file', {})` (espera `block` con gates sin cachear) y `_post_turn_guard('mcp__ultratimonel__end_turn', {}, {})` (espera `None`). Ver T6 por el snippet completo.
3. Inspección de firmas (`inspect.signature`) — sin `ctx` en `_gates_bouncer`/`_post_turn_guard` ni en `_on_session_start`/`_pre_llm_call` (F-SW-05/S5)
4. `diff -r skills/ ~/.hermes/skills/` — vacío para skills del repo
5. `ls ~/.hermes/skills/` — 4 skills presentes
6. Suite existente: `.venv/bin/pytest tests/ -q --tb=short` — sin regresiones
7. `openspec/config.yaml` alineado: `test_runner.framework: pytest`, `command: .venv/bin/pytest` (evita confundir al verificador)

---

## 6. Implementation Order

1. Fix hook signatures en `plugin_preflight.py` (ADR-2) + log `register()` → v2.0.1
2. Bump `plugin.yaml` → 2.0.1
3. Documentar la parametrización del cliente YA implementada (ADR-4, post-estado) — verificar `.env.example`; sin código nuevo
4. Sync skills repo → snapshot `~/.hermes/skills/` (ADR-1)
5. Copiar skills faltantes al snapshot (`opencode`, `pipeline-determinista-ui-code`) — fuente confirmada en apply-time (T2)
6. Registrar decisión `custom-dangerous-patterns` en ADR-3 + README (docs-only — sin manifest en repo)
7. Verificación post-cambio (sección 5)
8. Docs: README sección snapshot workflow (T7)

---

## 7. Open Questions

1. **`custom-dangerous-patterns` — RESUELTA (docs-only):** la dependencia NO existe en los manifests del repo (verificado en `requirements.txt`/`pyproject.toml`), así que no hay pin en repo que hacer. La decisión (default 0.3.4, flip a 1.6.0 solo con validación) se registra en ADR-3 + README. En apply-time (T5) se confirma la versión real del snapshot del otro Hermes para actualizar el texto documentado.
2. **Ubicación del snapshot — RESUELTA:** `~/.hermes/skills/` (confirmado en README sección "Instalar las skills del proyecto"). Sin placeholders `<snapshot>/`.
3. **Origen de skills faltantes — RESUELTA con default explícito (fuente != destino):** fuente primaria = skills dir del snapshot del OTRO Hermes — el `~/.hermes/skills/` de la otra máquina/otro usuario (p.ej. `hermes@otra-maquina:~/.hermes/skills/opencode`), NUNCA el `~/.hermes/skills/` local, que es el DESTINO del snapshot en este cambio. Fallback = repos upstream canónicos. T2 queda **blocked-by-decision**: el ejecutor confirma la fuente real al aplicar, exige `fuente != destino` antes de cualquier `cp`, y registra ambos en apply-progress. Sin placeholders `<snapshot>/`.
