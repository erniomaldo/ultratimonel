# Plugin Preflight Sync — Verify Report

## Evidencia verificada (dato real, no especular)

### 1. Identidad plugin repo ↔ runtime

- `ultratimonel/plugin_preflight.py` en el repo es IDENTICO a la versión que
  corría en runtime (copia instalada del agente, `__init__.py`).
- Diff vacio verificado (cuando runtime estaba disponible para comparar).
- El plugin en runtime fue parchado el 28-jul (`post_turn_guard` v2.0.0) sin
  reflejarse en el repo — el fix porto el runtime AL repo.

### 2. py_compile

```
python3 -m py_compile ultratimonel/ultratimonel_client.py → OK
python3 -m py_compile ultratimonel/plugin_preflight.py   → OK
```

Ambos archivos compilan sin errores de sintaxis.

### 3. Suite de tests existente

- 75/75 tests pasan en esta rama (suite del server: gate_engine, persistence,
  triple_match, context_extractor, server, integration).
- **NOTA:** No hay tests específicos para `plugin_preflight.py` en el directorio
  `tests/`. El plugin se prueba implícitamente via integración runtime con Hermes.

### 4. Estructura del plugin versionado

| Archivo | Versión | Hooks registrados |
|---------|---------|-------------------|
| `ultratimonel/plugin_preflight.py` | 2.0.0 | on_session_start, pre_llm_call, pre_tool_call, post_tool_call |
| `ultratimonel/plugin.yaml` | 2.0.0 | on_session_start, pre_llm_call, pre_tool_call, post_tool_call |
| `ultratimonel/ultratimonel_client.py` | — | cliente MCP stdio (importado por plugin) |

### 5. Comportamiento verificado en código

| Requisito | Estado | Evidencia |
|-----------|--------|-----------|
| 4 hooks registrados | ✅ | `register()` llama a los 4 `ctx.register_hook` |
| Bloqueo sin gates | ✅ | `_gates_bouncer` checkea `_last_gates_parsed is None` → block |
| Grace turns | ✅ | `_turn_count <= GRACE_TURNS` → permite execution |
| 4/4 complete_intento | ✅ | Check `gates_passed < 4` y `requested != 4` |
| Title lock | ✅ | `args.get("title")` → block en `deck_update_card` |
| 1 ciclo por respuesta | ✅ | `_post_turn_guard`: end_turn marca `_turn_ended=True`, bloquea todo tras eso |
| Env var GRACE_TURNS | ✅ | `int(os.environ.get("ULTRATIMONEL_GRACE_TURNS", "3"))` |
| Inyección de contexto | ✅ | `gates_summary_has_issues()` detecta BLOCK/WARN, inyecta resumen |

## Qué falta por verificar

| Ítem | Prioridad | Método | Estado |
|------|-----------|--------|--------|
| Tests unitarios del plugin | Alta | Crear `tests/test_plugin_preflight.py` con mocking de `ultratimonel_client` | ⏳ no existe |
| Carga desde repo tras deploy | Media | Verificar que el agente carga `plugin_preflight.py` desde la ruta del repo, no desde cache | ⏳ no verificado |
| post_turn_guard en runtime | Media | Ejecutar integración: begin_turn → trabajo → end_turn → tool2 debe bloquear | ⏳ no ejecutado |

## Conclusión

La implementación está correcta y sincronizada con el runtime. Los artefactos
SDD (proposal, specs, design, tasks) se crearon retrospectivamente para
documentar el change. Quedan pendientes tests unitarios del plugin y
verificación de carga desde repo tras deploy.
