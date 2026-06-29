# mcp-capabilities: Gate 1b.1

> **Estado:** Funcionando en este dispositivo · **Repo:** erniomaldo/mcp-capabilities-server
> **Path local:** ~/Proyectos/mcp-capabilities-server/

## ¿Qué es?

MCP server determinístico que indexa las tools de TODOS los MCP servers registrados en Hermes y expone búsqueda híbrida (semántica + FTS5).

No depende de skills ni de memoria — lee directo de `~/.hermes/config.yaml` y scrapea los servers vivos.

## Lo que cubre (Post-MVP)

Se integra como gate complementario al triple match. Mientras 1a/1b/1e responden "¿qué sabemos del usuario y el proyecto?", 1b.1 responde:

> "Para lo que el usuario quiere hacer, ¿qué tools existen y cuáles son las mejores?"

## Tools Expuestas

| Tool | Propósito |
|------|-----------|
| `search_capabilities(query, server?, limit?)` | Búsqueda semántica de tools |
| `refresh_index()` | Re-scrapea todos los servers |
| `list_servers()` | Servers indexados + conteo de tools |

## Integración con Ultratimonel

```yaml
gates:
  1b.1:
    source: mcp-capabilities
    tool: search_capabilities
    trigger: when user mentions a task/action
    frequency: per message
    fallback: skip if mcp-capabilities not available
```

## Pendiente para versión completa

- [ ] Historial de usos previos (trackear qué tools se usaron y su efectividad)
- [ ] Ranking por efectividad (no solo similitud vectorial)
- [ ] Auto-ejecutarse al iniciar sesión
