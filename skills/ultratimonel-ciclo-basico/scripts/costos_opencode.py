#!/usr/bin/env python3
"""Reporte de costo de un run de opencode en UN renglón.

Uso:  python3 costos_opencode.py "<fragmento-del-titulo>"

Flujo exacto (verificado 2026-08-11):
  - `opencode session list` NO muestra los runs -> buscar en la DB directo.
  - `opencode export <sid>` trae tokens en messages[i].info.tokens
    = {input, output, reasoning, cache:{read,write}} y costo real en info.cost.
  - Si costo real == $0 (modelo local) -> referencia kwaipilot
    (Qwen3.6 Plus <=256K: $0.50/M entrada, $3.00/M salida, $0.05 cache-read).
"""
import json
import os
import sqlite3
import subprocess
import sys

DB = os.path.expanduser("~/.local/share/opencode/opencode.db")


def find_sid(fragment: str):
    con = sqlite3.connect(DB)
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT id FROM session WHERE title LIKE ? ORDER BY rowid DESC LIMIT 1",
            (f"%{fragment}%",),
        )
        row = cur.fetchone()
    finally:
        con.close()
    return row[0] if row else None


def parse_export(path: str):
    # Pitfall 2026-08-12: `opencode export` antepone logs de plugins
    # (ej. [opencode-lmstudio] ...) antes del JSON — json.load directo falla.
    # Se salta todo hasta el inicio real del documento (la llave de apertura).
    raw = open(path).read()
    start = raw.find('"info"') - 1
    while start > 0 and raw[start] != "{":
        start -= 1
    data = json.loads(raw[start:])
    msgs = data.get("messages") or []
    tin = tout = treas = tcr = 0
    cost = 0.0
    for m in msgs:
        info = m.get("info") or (m.get("msg") or {}).get("info") or {}
        t = info.get("tokens") or {}
        tin += t.get("input", 0) or 0
        tout += t.get("output", 0) or 0
        treas += t.get("reasoning", 0) or 0
        cache = t.get("cache") or {}
        tcr += (cache.get("read", 0) if isinstance(cache, dict) else 0) or 0
        cost += info.get("cost", 0) or 0
    return len(msgs), tin, tout, treas, tcr, cost


def main():
    fragment = sys.argv[1] if len(sys.argv) > 1 else ""
    if not fragment:
        print("Uso: python3 costos_opencode.py \"<fragmento-del-titulo>\"")
        return 2
    sid = find_sid(fragment)
    if not sid:
        print("SESION_NO_ENCONTRADA — fallback: opencode stats --models 5 --days 1")
        return 1
    tmp = os.path.expanduser(f"~/.cache/oc_export_{os.getpid()}.json")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    # Redirect a archivo (probado 2026-08-11): capture_output trunca el JSON
    # en runs con dumps grandes; el redirect a archivo funciona.
    proc = subprocess.run(
        f'opencode export "{sid}" > "{tmp}" 2>/dev/null',
        shell=True,
        timeout=300,
    )
    if proc.returncode != 0 or not os.path.exists(tmp):
        print(f"EXPORT_FALLO (rc={proc.returncode})")
        return 1
    n, tin, tout, treas, tcr, cost = parse_export(tmp)
    ref = (tin / 1e6) * 0.50 + ((tout + treas) / 1e6) * 3.00 + (tcr / 1e6) * 0.05
    line = f"input: {tin} | output: {tout} (+{treas} reasoning) | costo: ${cost:.4f}"
    if cost == 0:
        line += f" (local) | ref kwaipilot: ${ref:.4f}"
    line += f" | mensajes: {n}"
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
