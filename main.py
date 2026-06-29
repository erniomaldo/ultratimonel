"""
main.py — Ultratimonel MCP server entry point.

Run directly:
    python main.py

Or via Hermes MCP config:
    {"command": "python", "args": ["/path/to/ultratimonel/main.py"]}
"""

import logging
import sys

from ultratimonel.server import app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)

if __name__ == "__main__":
    logging.getLogger("ultratimonel").info("Starting Ultratimonel MCP server…")
    app.run(transport="stdio")
