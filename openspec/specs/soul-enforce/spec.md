# Soul Enforce — SOUL.md Identity Hardening Rules

> **Capability ID:** `soul-enforce`
> **Status:** Draft · **Updated:** 28 Jun 2026
> **MVP:** Yes — enforcement capability

## 1. Purpose

Define the SOUL.md enforcement rules that make pre-flight gate checks a non-negotiable part of Hermes' identity. The SOUL.md file is always loaded regardless of working directory, making it the ideal location for hard behavioral rules that the agent cannot "forget" between sessions.

## 2. Requirements

### 2.1 Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| F-SE-01 | SOUL.md SHALL contain a dedicated `## Pre-flight Protocol` section with hard gate rules | MUST |
| F-SE-02 | The Pre-flight Protocol section SHALL be separate from personality/identity sections | MUST |
| F-SE-03 | The rules SHALL require calling `assert_gates()` before every generation | MUST |
| F-SE-04 | The rules SHALL state that generation is the **last** step, never the first | MUST |
| F-SE-05 | The rules SHALL require AgentMemory recall (gate 1a) before generation | MUST |
| F-SE-06 | The rules SHALL require Checkpoint status (gate 1b) before generation | MUST |
| F-SE-07 | The rules SHALL require Deck scan (gate 1e) before generation | MUST |
| F-SE-08 | The rules SHALL specify that BLOCK state halts generation immediately | MUST |
| F-SE-09 | SOUL.md SHALL be located at `~/.hermes/SOUL.md` | MUST |
| F-SE-10 | The rules SHALL be written in Spanish (neutral), direct and imperative tone | MUST |
| F-SE-11 | The rules SHALL use numbered, actionable instructions | MUST |
| F-SE-12 | The server SHALL NOT modify SOUL.md — rules are written manually or via deployment script | MUST |
| F-SE-13 | A deployment script SHALL be provided to inject/update the Pre-flight Protocol section | SHOULD |

### 2.2 Non-Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| NF-SE-01 | SOUL.md pre-flight rules SHALL persist across Hermes restarts and version upgrades | MUST |
| NF-SE-02 | SOUL.md rules SHALL be independent of project working directory | MUST |
| NF-SE-03 | Removal of pre-flight rules SHALL be a manual edit (not automated) for safety | MUST |
| NF-SE-04 | The SOUL.md rules SHALL NOT affect other agents or tools — only Hermes | MUST |

## 3. SOUL.md Rule Format

### 3.1 Required Section

The following section MUST be present in `~/.hermes/SOUL.md`:

```markdown
## Protocolo Pre-flight (OBLIGATORIO)

Antes de generar cualquier respuesta, DEBES ejecutar el pre-flight:

1. [1a] Llama a `assert_gates()` con el contexto del mensaje (sender, topic, project)
   - Esto ejecuta: AgentMemory recall, Checkpoint status, Deck scan
2. [1b] Si `assert_gates()` devuelve `status: "BLOCK"`, NO generes.
   - Informa al usuario qué gate bloqueó y por qué.
3. [1c] Si `assert_gates()` devuelve `status: "PASS"`, el contexto está listo.

REGLAS:
- La generación es SIEMPRE el último paso, nunca el primero.
- No infieras contexto de memoria anterior sin ejecutar gates.
- No saltes gates aunque "recuerdes" la información.
- Si un gate devuelve WARN, continúa pero menciona la advertencia.
- Si un gate devuelve SKIP, continúa — no es necesario reportarlo.
```

### 3.2 Placement Rules

- The section MUST be at the end of SOUL.md, after personality/identity sections
- A separator (`---`) SHOULD precede the section
- The section MUST NOT be inside any other section
- The section MUST NOT be commented out

## 4. Deployment Script Specification

While the spec does not mandate an automatic deployment mechanism, a helper script SHOULD be provided:

**Name:** `deploy-soul-rules.sh`
**Location:** `~/Proyectos/ultratimonel/scripts/`
**Behavior:**
1. Read `~/.hermes/SOUL.md`
2. If `## Protocolo Pre-flight (OBLIGATORIO)` section exists, update it in-place
3. If not, append the section after a `---` separator
4. Backup original SOUL.md to `~/.hermes/SOUL.md.bak.<timestamp>`
5. Exit with confirmation diff

## 5. Verification Procedure

After deployment, verify with a test session:

```
Given: A new Hermes session is started
When:  A simple message is sent (e.g., "Hello")
Then:  Hermes calls assert_gates() before generating
And:   The audit log shows gates 1a, 1b, 1e were executed
And:   The response includes context from the gates

Given: assert_gates() returns BLOCK for gate 1a
When:  Hermes attempts to generate
Then:  Generation is halted
And:  Hermes reports: "Gate 1a (AgentMemory) bloqueado — no se puede generar sin contexto de memoria"
```

## 6. Scenarios

### 6.1 Successful Gate Enforcement

```
Given: SOUL.md contains the Pre-flight Protocol section
Given: Hermes receives a user message
When:  Hermes processes the message
Then:  Hermes calls assert_gates() first
And:   Gates pass (PASS)
And:   Hermes generates the response with full context
```

### 6.2 Blocked Generation

```
Given: SOUL.md contains the Pre-flight Protocol section
Given: Gate 1b (Checkpoint) returns BLOCK
When:  assert_gates() returns status: "BLOCK"
Then:  Hermes does NOT generate a response
And:   Hermes informs the user which gate blocked and why
```

### 6.3 Agent Ignores Rules (Backup)

```
Given: SOUL.md contains the Pre-flight Protocol section
Given: Hermes generates without calling assert_gates()
When:  The response is delivered
Then:  The n8n backup pipeline detects the missing gate call
And:   An alert is logged in the Nextcloud docs strategy
And:   Hermes configuration is flagged for review
```

### 6.4 Rules Not Present

```
Given: SOUL.md does NOT contain the Pre-flight Protocol section
When:  A session starts
Then:  There is no enforcement of pre-flight gates
And:   The agent may generate without context
And:   This is a known degraded state — deployment script must be run
```

### 6.5 Rollback — Rules Removed

```
Given: The Pre-flight Protocol section is manually removed from SOUL.md
When:  The next session starts
Then:  Hermes operates without gate enforcement
And:   No other system is affected
And:   The rollback plan is complete
```

## 7. Error Handling

| Condition | Action | Notes |
|-----------|--------|-------|
| SOUL.md does not exist | Create it with the Pre-flight Protocol section | Initial setup |
| SOUL.md has conflicting instructions | Pre-flight Protocol section takes precedence for gate behavior | Explicit ordering rule |
| Backup fails during deployment | Abort change, report error | Safety first |
| Multiple Pre-flight sections | Remove duplicates, keep the last occurrence | Cleanup rule |
