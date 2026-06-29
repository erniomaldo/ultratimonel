# SOUL.md Enforcement

> **Propósito:** Reglas duras en la identidad del agente que exigen llamar a las gates antes de inferir.

## Regla Base

El SOUL.md debe contener una regla explícita y no negociable:

```markdown
## Pre-flight Protocol (OBLIGATORIO)

Antes de generar cualquier respuesta, DEBES ejecutar el pre-flight:

1. [1a] Llama a `mcp_agentmemory_memory_recall` con el sender/tópico
2. [1b] Llama a `mcp_checkpoint_get_state` con el proyecto activo
3. [1e] Escanea cards pendientes en Nextcloud Deck
4. [Opcional] Si aplica, consulta `search_capabilities` en mcp-capabilities

Si algún gate falla, NO generes — ejecuta el gate automáticamente o informa al usuario.

La generación es SIEMPRE el último paso, nunca el primero.
```

## Ubicación

`~/.hermes/SOUL.md` — siempre cargado, independiente del directorio de trabajo.

## Formato Esperado

- Idioma: Español (neutral)
- Tono: Directo, imperativo
- Sección separada, no mezclada con personalidad
- Instrucciones numeradas y accionables

## Verificación

Después de implementar, verificar con una sesión de prueba:
1. Iniciar sesión nueva
2. Preguntar algo simple
3. Confirmar que las gates se ejecutaron antes de generar
4. Si no — ajustar el prompt hasta que sea consistente
