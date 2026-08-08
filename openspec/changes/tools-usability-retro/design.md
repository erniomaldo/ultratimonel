# Design: Tools Usability Retro (Card #147)

> **Change:** `tools-usability-retro` · **Date:** 2026-08-07 · **Capability:** `tools-usability` + `begin-turn-project-fix`
> **Inputs:** [proposal.md](./proposal.md) · [spec.md](./specs/tools-usability/spec.md)

---

## 1. Architecture Decision Records

### ADR-1: `mission_get` + `checklist_item_get` como tools MCP separadas vs filtros en `mission_list`

**Contexto:** Hermes necesita recuperar una misión o item específico sin fetchear todo el proyecto. La alternativa sería añadir filtros a `mission_list` (ej. `mission_list(project, id=123)`).

**Decisión:** Crear dos tools MCP independientes: `mission_get(mission_id)` y `checklist_item_get(checklist_item_id)`.

**Justificación:**

| Criterio | Filtros en `mission_list` | Tools separadas |
|----------|---------------------------|-----------------|
| Superficie de herramientas | Menos tools, más params | Más tools, cada uno con responsabilidad clara |
| Claridad semántica | `mission_list(project, id=123)` es ambiguo (¿lista o get?) | Nombre del tool comunica la intención |
| Rendimiento | Siempre hace JOIN con checklist_items (a menos que se opte por light mode) | Query directa por PK, sin joins innecesarios |
| Backward compatibility | Modifica `mission_list` sig → riesgo de breaking | 100% aditivo, cero impacto en callers existentes |
| Testabilidad | Caso mixto dentro de test existente | Test aislado, fixture simple |

**Riesgo aceptado:** Aumentar la superficie de tools MCP en 2. Mitigación: son tools internas (solo Hermes las llama), y cada una tiene schema simple con un solo param entero.

**Query resultante:**
```python
# server.py
@app.tool()
def mission_get(mission_id: int) -> str:
    """Retrieve a single mission by ID with minimal fields."""
    mission = persistence.get_mission_by_id(mission_id)
    if not mission:
        return json.dumps({"error": f"Mission {mission_id} not found"})
    return json.dumps({
        "id": mission["id"],
        "title": mission["title"],
        "checklist_item_ids": [
            ci["id"] for ci in persistence.list_checklist_items(mission["id"])
        ],
    }, ensure_ascii=False, default=str)

@app.tool()
def checklist_item_get(checklist_item_id: int) -> str:
    """Retrieve a single checklist item by ID."""
    with persistence._lock:
        with persistence._conn() as conn:
            row = conn.execute(
                "SELECT * FROM checklist_items WHERE id = ?",
                (checklist_item_id,),
            ).fetchone()
    if not row:
        return json.dumps({"error": f"Checklist item {checklist_item_id} not found"})
    return json.dumps(dict(row), ensure_ascii=False, default=str)
```

**Alternativa descartada:** Añadir `id` filter a `mission_list`. Se descarta porque (a) mezcla semántica list/get, (b) no resuelve el caso de checklist_item_get que requiere tabla diferente, (c) aumenta complejidad en una función ya grande.

---

### ADR-2: `include_description=false` como opt-in para light mode; default = full payload (F-TU-07)

**Contexto:** `mission_list` devuelve payloads completos (description + nested checklist_items). Hermes solo necesita id/title/status para navegación. El dashboard sigue necesitando el payload completo. F-TU-07 exige que el default permanezca como full payload para backward compatibility con consumidores existentes del dashboard.

**Decisión:** Añadir parámetro opcional `include_description: bool = True` a `mission_list`. **Default es `True`** — full payload (comportamiento actual, backward compatible). Light mode se activa explícitamente con `include_description=False`.

> ✅ **Conformidad con F-TU-07:** "Default behavior of mission_list SHALL remain full payload (backward compatible with dashboard consumers); include_description=false is an opt-in for lightweight mode". Default=True cumple literalmente el spec. Hermes pasa `include_description=False` cuando necesita light mode.

**Implementación:**
```python
@app.tool()
def mission_list(project: str, include_description: bool = True) -> str:
    """List missions for a project.
    
    Args:
        project: Project slug.
        include_description: If True (default), returns full payload
            including description and nested checklist_items (backward compatible).
            When False, returns lightweight {id, title, status} per mission.
    """
    missions = persistence.list_missions(project)
    
    if not include_description:
        # Light mode: strip heavy fields
        light_missions = [
            {"id": m["id"], "title": m["title"], "status": m["status"]}
            for m in missions
        ]
        payload = {
            "project": project,
            "missions": light_missions,
            "total": len(light_missions),
        }
    else:
        # Full mode: current behavior (missions already include checklist_items)
        payload = {
            "project": project,
            "missions": missions,
            "total": len(missions),
        }
    
    return json.dumps(payload, ensure_ascii=False, default=str)
```

**Impacto en dashboard:** Cero. El dashboard que llama `mission_list(project)` sin el nuevo parámetro recibe exactamente el mismo payload que antes — full payload con description y checklist_items. 100% backward compatible.

**Impacto en Hermes:** Hermes debe pasar `include_description=False` explícitamente cuando necesite light mode (navegación rápida). Esto es un cambio de llamada, no de API shape.

**Alternativa descartada:** Default=False con parámetro `exclude_description`. Se descarta porque F-TU-07 exige explicitamente que el default sea full payload.

---

### ADR-3: Fix de project en `begin_turn` — preferir param explícito sobre context extraction

**Contexto:** En `server.py:1255` (original), `resolved_project = context["project"]` ignora completamente el parámetro `project` pasado por Hermes. Cuando la extracción de contexto resuelve a `"unknown"`, salen dos problemas:

1. **Persistencia:** los gates se persisten bajo project `"unknown"` y `end_turn` valida contra ese project incorrecto (arreglado parcialmente por el commit `1cb0567`).
2. **Ejecución (bug raíz):** `run_triple_match(context)` usa `context["project"]` para ejecutar los gates, así que 1c/1e corren contra `"unknown"` y SKIPean ("No collective/Deck board mapped for project unknown") aunque `begin_turn` haya recibido un project explícito correcto. Reproducido en intento #234.

**Decisión (fix completo, commit `fb51b44`):** Resolver `resolved_project` ANTES de `run_triple_match` y pisar `context["project"]` con el project resuelto. Los gates 1c/1e leen `context["project"]` para buscar sus maps (`get_project_maps()`), así que al sobrescribirlo ejecutan contra el project correcto:
```python
# ANTES DE run_triple_match(context) — server.py, begin_turn
resolved_project = project if project else context["project"]
context["project"] = resolved_project   # los gates 1c/1e ejecutan contra el project resuelto
```

**Análisis del fallback:**
- `project=""` → usa `context["project"]` (fallback a extracción heurística)
- `project="voy-rojo"` → usa `"voy-rojo"` directamente
- `project` con valor por defecto de MCP (`""`) → mismo que empty string

**Escenarios cubiertos:**

| Escenario | `project` arg | `context["project"]` | Resultado |
|-----------|--------------|---------------------|-----------|
| Hermes pasa project correcto | `"voy-rojo"` | `"unknown"` | `"voy-rojo"` ✅ |
| Hermes pasa empty string | `""` | `"ultratimonel"` | `"ultratimonel"` (fallback) ✅ |
| Hermes no pasa project (legacy) | `""` | `"some-project"` | `"some-project"` ✅ |
| Ambos vacíos | `""` | `""` | `""` (degrade gracefully) ✅ |

**Impacto en callers existentes:** Cualquier caller que pasara un `project` explícito con valor real ya estaba esperando que se usara ese valor. El bug hacía que el parámetro fuera ignorado. Este fix alinea el comportamiento con la semántica esperada del parámetro.

**Testing:** Ver sección 5 (Impacto en tests). Se requieren tests de regresión S7+S8+S9 (persistencia) y S9-ejecución+S10 (ejecución de gates contra el project resuelto).

---

### ADR-4: Ubicación de las queries nuevas en `persistence.py`

**Contexto:** `persistence.py` ya tiene `get_mission(mission_id)` que retorna el registro completo de la tabla `missions`. No existe `get_checklist_item_by_id`.

**Decisión:**
1. **`get_mission_by_id`**: Renombrar `get_mission` → `get_mission_by_id` (alias backward compat) o crear nueva función. Dado que `get_mission` ya existe y hace exactamente lo que necesitamos (query por PK), **no se crea nueva función** — se reusa `get_mission`.
2. **`get_checklist_item_by_id`**: Crear nueva función siguiendo el patrón existente de queries por PK (`get_session`, `get_intento`).

**Ubicación en `persistence.py`:** Dentro del bloque `# ── checklist_items ─────────────────────────────────────────────────`, inmediatamente después de `list_checklist_items`:

```python
def get_checklist_item_by_id(self, checklist_item_id: int) -> Optional[dict]:
    """Retrieve a single checklist item by its primary key."""
    with self._lock:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, mission_id, item_index, text, done"
                " FROM checklist_items WHERE id = ?",
                (checklist_item_id,),
            ).fetchone()
            return dict(row) if row else None
```

**Nota de performance:** La query selecciona columnas explícitas en lugar de `SELECT *` para reducir transferencia de datos. El campo `done` es INTEGER (0/1), no requiere transformación.

**Alternativa descartada:** Usar `list_checklist_items(mission_id)` + filtrado en Python. Se descarta porque (a) requiere conocer el mission_id de antemano, (b) carga todos los items de la misión cuando solo se necesita uno, (c) viola NF-TU-01 (<5ms).

---

## 2. Component Design

### 2.1 New Tools in `server.py`

**Location:** Lines ~1170 (after `mission_list`, before `begin_turn`)

```
server.py
├── assert_gates          (line 173)
├── complete_gate         (line 328)
├── ...
├── mission_list          (line 1151) ← MODIFIED: add include_description param
├── mission_get           (line ~1170) ← NEW
├── checklist_item_get    (line ~1180) ← NEW
└── begin_turn            (line 1175) ← MODIFIED: line 1255 project resolution
```

### 2.2 Persistence Layer Changes

**`persistence.py`:**
- `get_mission(mission_id)` → reutilizar tal cual (ya existe, línea 702)
- Nueva función `get_checklist_item_by_id(checklist_item_id)` después de `list_checklist_items` (línea 786)

### 2.3 Test Changes

**`tests/test_server.py`:**

| Nueva clase | Tests | Cubre |
|-------------|-------|-------|
| `TestMissionGet` | 2 | Happy path + not found (F-TU-01, F-TU-05) |
| `TestChecklistItemGet` | 2 | Happy path + not found (F-TU-02, F-TU-06) |
| `TestMissionListLightMode` | 2 | Default full payload + opt-in light mode (F-TU-03, F-TU-07) |
| `TestBeginTurnProjectFix` | 5 | Explicit project wins, empty fallback, end_turn validation (S7, S8, S9) + ejecución de gates contra project explícito y fallback (S9-ejecución, S10) |

**`tests/test_persistence.py`:**
- Clase `TestChecklistItemsById` → 2 tests (found + not found)

### 2.4 Integration Test Strategy

Los tests de integración (`test_integration.py`) deben agregar:
- `test_mission_get_returns_minimal_fields` — llamada real vía MCP client
- `test_mission_list_light_mode_omits_description` — llamada real con `include_description=false`
- `test_begin_turn_persists_explicit_project` — begin_turn con project explícito + end_turn validando gates contra ese project

---

## 3. Data Flow Diagrams

### 3.1 `mission_get` flow

```
Hermes → mission_get(mission_id=123)
    │
    ├─→ persistence.get_mission(123)        # SELECT * FROM missions WHERE id=?
    │       └─→ {id:123, title:"...", description:"...", ...}
    │
    ├─→ persistence.list_checklist_items(123)  # SELECT FROM checklist_items WHERE mission_id=?
    │       └─→ [{id:456,...}, {id:457,...}]
    │
    └─→ Response: {id:123, title:"...", checklist_item_ids:[456,457]}
```

### 3.2 `begin_turn` project resolution flow (post-fix `fb51b44`)

```
begin_turn(session_id, project="voy-rojo", ..., message="talk about unknown topic")
    │
    ├─→ extract_context(message) → {project: "unknown", ...}
    │
    ├─→ resolved_project = project if project else context["project"]   → "voy-rojo"
    │       └─→ context["project"] = "voy-rojo"   (sobrescribe "unknown")
    │
    ├─→ run_triple_match(context)   # los gates ejecutan contra "voy-rojo"
    │       └─→ 1c → collective_id=6, 1e → deck_board_id=7   (NO SKIP por "unknown")
    │
    └─→ persiste gates (gate_state) + intento bajo "voy-rojo"
```

### 3.3 `mission_list` dual-mode flow

```
mission_list(project="voy-rojo")                           ← default (F-TU-07)
    │
    ├─→ persistence.list_missions("voy-rojo")
    │       └─→ [{id:1, title:"A", description:"...", checklist_items:[...]}, ...]
    │
    └─→ include_description=True → full payload (current behavior, backward compatible)
        Response: {project, missions:[{id,title,description,...,checklist_items}], total:N}

mission_list(project="voy-rojo", include_description=False)  ← Hermes opt-in (light mode)
    │
    └─→ if not include_description:
            └─→ strip to {id, title, status} per mission
                Response: {project, missions:[{id,title,status}], total:N}
```

---

## 4. Risk Matrix

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|------------|--------|------------|
| R1 | Dashboard consumers unaffected — default is full payload (F-TU-07) | None | None | Default=True preserves exact current behavior. Zero breaking change for dashboard. |
| R2 | `mission_get` exposes internal mission IDs to Hermes | Low | Low | Tools son internas MCP; minimal fields (no description) reducen superficie |
| R3 | `get_checklist_item_by_id` no existe en schema v1 DBs | Low | Low | Schema v3 es actual; migration path no requerido (tabla `checklist_items` ya existe desde v2) |
| R4 | Fix de project cambia comportamiento para callers legacy que pasaban `project=""` esperando fallback a context | Medium | Low | El comportamiento actual (ignorar param) ya era un bug; el fix alinea con semántica esperada. Callers legacy deben pasar project explícito si lo desean. |
| R5 | RLock deadlock en nueva query de `mission_get` que llama `list_checklist_items` | Low | Medium | `persistence._conn()` ya usa RLock; `list_checklist_items` también usa `with self._lock`. Como `mission_get` se llama desde tool handler (no desde otro método persistence), no hay anidamiento. Si se necesitara, usar `_conn()` directo en lugar de métodos públicos. |

---

## 5. Test Impact Analysis

### 5.1 Existing tests that may need updates

| Test | Change needed? | Reason |
|------|---------------|--------|
| `test_begin_turn_executes_fresh_gates` (line 296) | **Yes** | Assert line 328: `assert create_call[1]["project"] == "voy-rojo"` — con el fix, el project viene del arg `project`, no de `mock_extract`. El test ya pasa `"voy-rojo"` como arg Y como context, así que **no cambia el resultado**, pero la aserción debería verificar que el param explícito se prefiera. |
| `test_begin_turn_returns_context_info` (line 447) | **No** | Test valida campos de context en response, no project resolution. |
| `test_end_turn_success_4_4` (line 548) | **No** | Usa mocks directos, no toca begin_turn project resolution. |
| `TestMissions.test_list_missions_for_project` (test_persistence.py:172) | **No** | No toca `mission_list` tool sig. |

### 5.2 New tests required

**`tests/test_server.py`:**

```python
class TestMissionGet:
    @patch("ultratimonel.server.persistence")
    def test_mission_get_returns_minimal_fields(self, mock_persistence):
        """F-TU-01: mission_get returns id, title, checklist_item_ids only."""
        from ultratimonel.server import mission_get
        mock_persistence.get_mission.return_value = {"id": 123, "title": "Sprint Planning", "description": "..."}
        mock_persistence.list_checklist_items.return_value = [{"id": 456}, {"id": 457}]
        
        result = json.loads(mission_get(123))
        assert result == {"id": 123, "title": "Sprint Planning", "checklist_item_ids": [456, 457]}
        assert "description" not in result
        assert "checklist_items" not in result

    @patch("ultratimonel.server.persistence")
    def test_mission_get_not_found(self, mock_persistence):
        """F-TU-05: returns error for non-existent mission."""
        from ultratimonel.server import mission_get
        mock_persistence.get_mission.return_value = None
        
        result = json.loads(mission_get(9999))
        assert "error" in result
        assert "9999" in result["error"]


class TestChecklistItemGet:
    @patch("ultratimonel.server.persistence")
    def test_checklist_item_get_returns_item(self, mock_persistence):
        """F-TU-02: returns item by ID."""
        from ultratimonel.server import checklist_item_get
        mock_persistence.get_checklist_item_by_id.return_value = {
            "id": 456, "mission_id": 123, "item_index": 1, "text": "Review backlog", "done": 0
        }
        
        result = json.loads(checklist_item_get(456))
        assert result["id"] == 456
        assert result["text"] == "Review backlog"

    @patch("ultratimonel.server.persistence")
    def test_checklist_item_get_not_found(self, mock_persistence):
        """F-TU-06: returns error for non-existent item."""
        from ultratimonel.server import checklist_item_get
        mock_persistence.get_checklist_item_by_id.return_value = None
        
        result = json.loads(checklist_item_get(9999))
        assert "error" in result


class TestMissionListLightMode:
    @patch("ultratimonel.server.persistence")
    def test_default_returns_full_payload_backward_compatible(self, mock_persistence):
        """F-TU-07: default (no param) returns full payload — dashboard unchanged."""
        from ultratimonel.server import mission_list
        full_mission = {"id": 1, "title": "A", "description": "desc", "status": "pendiente", "checklist_items": [{"id": 10}]}
        mock_persistence.list_missions.return_value = [full_mission]

        result = json.loads(mission_list("testproj"))
        assert result["missions"][0]["description"] == "desc"
        assert result["missions"][0]["checklist_items"] == [{"id": 10}]
        assert result["total"] == 1

    @patch("ultratimonel.server.persistence")
    def test_include_description_false_returns_light_mode(self, mock_persistence):
        """F-TU-03: opt-in light mode omits description and checklist_items."""
        from ultratimonel.server import mission_list
        full_mission = {"id": 1, "title": "A", "description": "desc", "status": "pendiente", "checklist_items": [{"id": 10}]}
        mock_persistence.list_missions.return_value = [full_mission]

        result = json.loads(mission_list("testproj", include_description=False))
        assert result["missions"][0] == {"id": 1, "title": "A", "status": "pendiente"}
        assert "description" not in result["missions"][0]
        assert "checklist_items" not in result["missions"][0]


class TestBeginTurnProjectFix:
    @patch("ultratimonel.server.run_triple_match")
    @patch("ultratimonel.server.extract_context")
    @patch("ultratimonel.server.persistence")
    def test_explicit_project_wins_over_context(self, mock_persistence, mock_extract, mock_triple):
        """S7: explicit project param preferred over context extraction."""
        from ultratimonel.server import begin_turn
        from ultratimonel.gate_engine import GateResult, PASS, SKIP
        
        # Context extraction would return "unknown"
        mock_extract.return_value = {"sender": "user", "topic": "test", "project": "unknown"}
        mock_triple.return_value = [
            GateResult(name="1a", state=PASS), GateResult(name="1b", state=PASS),
            GateResult(name="1c", state=SKIP), GateResult(name="1e", state=PASS),
        ]
        mock_persistence.create_intento.return_value = 70
        
        result = json.loads(begin_turn("sess-x", "voy-rojo", 5, 10, "some context extracting unknown", "user"))
        
        # Verify create_intento was called with explicit project, not "unknown"
        create_call = mock_persistence.create_intento.call_args
        assert create_call[1]["project"] == "voy-rojo"
        
        # Verify gate_state upsert also used "voy-rojo"
        upsert_calls = mock_persistence.upsert_gate_state.call_args_list
        for call in upsert_calls:
            assert call[1]["project"] == "voy-rojo"

    @patch("ultratimonel.server.run_triple_match")
    @patch("ultratimonel.server.extract_context")
    @patch("ultratimonel.server.persistence")
    def test_empty_project_falls_back_to_context(self, mock_persistence, mock_extract, mock_triple):
        """S9: empty project param falls back to context extraction."""
        from ultratimonel.server import begin_turn
        from ultratimonel.gate_engine import GateResult, PASS, SKIP
        
        mock_extract.return_value = {"sender": "user", "topic": "test", "project": "ultratimonel"}
        mock_triple.return_value = [
            GateResult(name="1a", state=PASS), GateResult(name="1b", state=PASS),
            GateResult(name="1c", state=SKIP), GateResult(name="1e", state=PASS),
        ]
        mock_persistence.create_intento.return_value = 71
        
        begin_turn("sess-x", "", 5, 10, "talk about ultratimonel", "user")
        
        create_call = mock_persistence.create_intento.call_args
        assert create_call[1]["project"] == "ultratimonel"

    @patch("ultratimonel.server.persistence")
    def test_end_turn_validates_against_persisted_project(self, mock_persistence):
        """S8: end_turn gates validated against correct project (regression)."""
        from ultratimonel.server import begin_turn, end_turn
        
        # Simulate: begin_turn persisted intento with project="voy-rojo"
        mock_persistence.get_intento.return_value = {
            "id": 70, "session_id": "sess-x", "project": "voy-rojo"
        }
        mock_persistence.list_gate_states.return_value = [
            {"gate_name": "1a", "state": "PASS", "mandatory": 1},
            {"gate_name": "1b", "state": "PASS", "mandatory": 1},
            {"gate_name": "1c", "state": "SKIP", "mandatory": 0},
            {"gate_name": "1e", "state": "PASS", "mandatory": 1},
        ]
        mock_persistence.create_intento.return_value = 70
        
        begin_turn("sess-x", "voy-rojo", 5, 10, "msg", "user")
        result = json.loads(end_turn(70))
        
        assert result["final_status"] == "success"
        # Verify list_gate_states was called with correct project
        list_call = mock_persistence.list_gate_states.call_args
        assert list_call[1]["project"] == "voy-rojo" or list_call[0][1] == "voy-rojo"
```

> **Retrospectiva (`fb51b44`):** El diseño original preveía 3 tests de persistencia. El fix de EJECUCIÓN agregó 2 tests que verifican que `run_triple_match` recibe `context["project"]` con el project correcto (no `"unknown"`):
> - `test_gates_execute_against_explicit_project` — S10: extract→`"unknown"`, project="voy-rojo", assert `mock_triple.call_args[0][0]["project"] == "voy-rojo"`
> - `test_gates_execute_with_fallback_to_context` — S9-ejecución: project="", extract→`"ultratimonel"`, assert `context["project"] == "ultratimonel"`
>
> **Verificación:** 132 unit tests pasan (0 failures) + E2E en producción (intento #236: mensaje neutro + project='voy-rojo' → 1b checkpoint 'voy-rojo', 1c collective 6, 1e board 7 — sin SKIP por "unknown").

**`tests/test_persistence.py`:**

```python
class TestChecklistItemById:
    def test_get_checklist_item_by_id(self, db):
        mid = db.upsert_mission(deck_task_id=1, project="p", title="T")
        cid = db.upsert_checklist_item(mid, item_index=0, text="Item 1")
        item = db.get_checklist_item_by_id(cid)
        assert item is not None
        assert item["id"] == cid
        assert item["text"] == "Item 1"
        assert item["mission_id"] == mid

    def test_get_checklist_item_by_id_not_found(self, db):
        assert db.get_checklist_item_by_id(99999) is None
```

---

## 6. Implementation Order

1. **`persistence.py`** — Add `get_checklist_item_by_id()` (ADR-4)
2. **`server.py`** — Modify `mission_list` signature + light-mode branch (ADR-2)
3. **`server.py`** — Add `mission_get` tool (ADR-1)
4. **`server.py`** — Add `checklist_item_get` tool (ADR-1)
5. **`server.py`** — Fix project resolution in `begin_turn` line 1255 (ADR-3)
6. **`tests/test_persistence.py`** — Add `TestChecklistItemById`
7. **`tests/test_server.py`** — Add `TestMissionGet`, `TestChecklistItemGet`, `TestMissionListLightMode`, `TestBeginTurnProjectFix`
8. **`tests/test_integration.py`** — Add integration tests for new tools

---

## 7. Open Questions

1. **F-TU-07 default interpretation:** ✅ RESUELTO. Default = `True` (full payload, backward compatible). Light mode es opt-in via `include_description=False`. El proposal decía `default=False` pero F-TU-07 tiene prioridad MUST sobre el proposal. ADR-2 documentado con justificación.
2. **`mission_get` checklist_item_ids:** ¿Incluir IDs de items o solo count? El spec dice `checklist_item_ids` (lista). Se implementa como lista de IDs para dar a Hermes info suficiente sin payload completo.
