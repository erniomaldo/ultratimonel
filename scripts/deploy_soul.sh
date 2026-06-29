#!/usr/bin/env bash
# deploy_soul.sh — Inject Ultratimonel pre-flight gate rules into ~/.hermes/SOUL.md
#
# Safety:
#   1. Backs up original SOUL.md to ~/.hermes/SOUL.md.bak.<timestamp>
#   2. Checks if "Protocolo Pre-flight" section exists → update in-place
#   3. If not, appends the section after a "---" separator
#   4. Idempotent — safe to run multiple times
#
# Usage:
#   ./deploy_soul.sh                # normal mode (diff + confirm)
#   ./deploy_soul.sh --force        # skip confirmation
#   ./deploy_soul.sh --dry-run      # show changes without writing

set -euo pipefail

SOUL=~/.hermes/SOUL.md
FORCE=false
DRY_RUN=false

# Parse flags
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=true ;;
    --dry-run) DRY_RUN=true ;;
  esac
done

# Rules section content (Spanish imperative — per SDD §7)
read -r -d '' RULES_SECTION << "SECTION" || true

---

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
SECTION

# Ensure parent dir exists
mkdir -p "$(dirname "$SOUL")"

# Compute the section marker (first line, trimmed)
SECTION_MARKER="## Protocolo Pre-flight (OBLIGATORIO)"

# Dry-run: show diff and exit
if $DRY_RUN; then
  echo "[DRY-RUN] Would inject pre-flight rules into ${SOUL}"
  if [ -f "$SOUL" ]; then
    if grep -qF "$SECTION_MARKER" "$SOUL"; then
      echo "  → Section already exists (would update in-place)"
    else
      echo "  → Section would be appended"
    fi
    echo ""
    echo "--- Proposed content ---"
    echo "$RULES_SECTION"
  else
    echo "  → File does not exist, would create with rules"
    echo "$RULES_SECTION"
  fi
  exit 0
fi

# Backup
if [ -f "$SOUL" ]; then
  BAK="${SOUL}.bak.$(date +%Y%m%d-%H%M%S)"
  cp "$SOUL" "$BAK"
  echo "[BACKUP] Created ${BAK}"
fi

# Check if section exists
if [ -f "$SOUL" ] && grep -qF "$SECTION_MARKER" "$SOUL"; then
  # Replace existing section using sed (from marker to next --- or end)
  if $FORCE; then
    # Use a temp file approach with awk for reliability
    awk -v marker="$SECTION_MARKER" -v rules="$RULES_SECTION" '
      $0 ~ marker { found=1; print rules; next }
      found && /^---$/ { found=0; next }
      found { next }
      { print }
    ' "$SOUL" > "${SOUL}.tmp" && mv "${SOUL}.tmp" "$SOUL"
    echo "[UPDATED] Pre-flight rules updated in-place"
  else
    echo "[SKIP] Section already exists. Use --force to update."
    echo "  Current rules in ${SOUL}"
    echo "  Backup: ${BAK}"
    exit 0
  fi
else
  # Append rules
  if [ -f "$SOUL" ]; then
    echo "" >> "$SOUL"
    echo "$RULES_SECTION" >> "$SOUL"
  else
    echo "$RULES_SECTION" > "$SOUL"
  fi
  echo "[INJECTED] Pre-flight rules appended to ${SOUL}"
fi

# Show confirmation
echo ""
echo "=== Confirmation (last 10 lines) ==="
tail -10 "$SOUL"
