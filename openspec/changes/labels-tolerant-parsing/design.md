# labels-tolerant-parsing — Design

## ADR-009: Parsing tolerante de labels (str o dict) en triple_match

**Contexto:** El gate 1e (`_call_deck`) en `ultratimonel/triple_match.py` parsea
labels de cards de Nextcloud Deck. Diferentes deployments del MCP de Nextcloud
devuelven labels en formatos distintos: algunos como strings, otros como dicts
con campos `id`, `title`, `color`, etc. El código actual asume dict → crash con
strings (`'str' object has no attribute 'get'`).

**Alternativas consideradas:**

1. **Normalizar en el MCP de Nextcloud** — forzar que el servidor siempre devuelva
   dicts. Trade-off: requiere cambios en el servidor externo, no controlable desde
   este repo; los deployments existentes seguirían rompiendo hasta que se actualice.
2. **Tolerar en el repo (consumidor)** — hacer el parse robusto a ambos formatos.
   Trade-off: cero cambios en el servidor, funciona con todos los deployments
   inmediatamente; código ligeramente más defensivo pero claro.

**Decisión:** Opción 2. Tolerar en el repo. Rationale:
- El repo es el consumidor; la tolerancia es responsabilidad del que parsea.
- No requiere coordinación con admins de Nextcloud (multi-servidor).
- Fix mínimo, localizado, fácil de testear.
- El patrón `isinstance(x, dict) ? x["title"] : str(x)` es estándar y explícito.

**Implementación:**

```python
# Antes:
"labels": [l.get("title", "") for l in (card.get("labels") or [])],

# Después:
"labels": [l["title"] if isinstance(l, dict) else str(l) for l in (card.get("labels") or [])],
```

**Consecuencias:**
- Labels como dicts → se extrae `title`.
- Labels como strings → se usa el string tal cual.
- Labels null/empty → `[]` (sin cambio).
- No hay riesgo de regressión: el `or []` ya protegía contra None; ahora también
  protege contra str elements.
