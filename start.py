"""
Startup wrapper — sets the Windows event loop policy BEFORE uvicorn starts,
then boots the FastAPI app.

Module Purpose & Role in the Project:
------------------------------------
This module is the entry point for starting the FastAPI backend application on local environments,
especially on Windows platforms. Under Python on Windows, the default asyncio event loop
(ProactorEventLoop) has known incompatibilities with asynchronous PostgreSQL socket drivers
like `psycopg` (v3 async). `start.py` explicitly overrides the asyncio event loop policy to
`WindowsSelectorEventLoopPolicy` prior to importing or launching Uvicorn and FastAPI.

Interconnections with Other Components:
---------------------------------------
- `app.main:app`: Imports the initialized FastAPI application instance containing all routers,
  lifespan handlers (database connection pools, MinIO clients, vector store setup), and middleware.
- `app.core.database`: Benefits from `WindowsSelectorEventLoopPolicy` for non-blocking database queries.
- `uvicorn`: ASGI server library executed in-process to listen on `127.0.0.1:8000`.
- Streamlit UI (`app.py`): Connects to the server booted by this script at `http://localhost:8000/api/v1`.

Usage:
  # Option 1: Use the venv Python (recommended — no activation needed)
  venv\\Scripts\\python.exe start.py

  # Option 2: Activate venv first, then run normally
  .\\venv\\Scripts\\activate
  python start.py
"""
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
    """
    Start the Uvicorn ASGI server hosting the FastAPI backend application.

    Interconnections:
    - Hosts: `app.main:app` which mounts endpoints for auth, documents, chat,
      applications, and service management.
    - Network: Listens on IPv4 loopback `127.0.0.1:8000`.
    - Called By: Root execution block `if __name__ == '__main__':`.
    """
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )

if __name__ == "__main__":
    run_server()
