"""Startup wrapper — sets the Windows event loop policy BEFORE uvicorn starts,"""
import sys
import os

# Resolve paths relative to this script's directory ensuring correct root context
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)

# On Windows, switch to SelectorEventLoopPolicy (required for psycopg async)
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn
from app.main import app

def run_server() -> None:
    """Start the Uvicorn ASGI server hosting the FastAPI backend application."""
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )

if __name__ == "__main__":
    run_server()
