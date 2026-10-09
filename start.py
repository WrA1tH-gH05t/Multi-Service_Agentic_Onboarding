"""
Startup wrapper — sets the Windows event loop policy BEFORE uvicorn starts,
then boots the FastAPI app.

Usage:
  # Option 1: Use the venv Python (recommended — no activation needed)
  venv\\Scripts\\python.exe start.py

  # Option 2: Activate venv first, then run normally
  .\\venv\\Scripts\\activate
  python start.py
"""
import sys
import os

# Resolve paths relative to this script's directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)

# On Windows, switch to SelectorEventLoopPolicy (required for psycopg async)
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn
from app.main import app

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )
