"""Startup wrapper — sets Windows event loop policy, ensures Docker and Ollama services are running, and starts Uvicorn."""
import sys
import os
import subprocess
import time
import shutil
import urllib.request
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("startup")

# Resolve paths relative to this script's directory ensuring correct root context
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)

# On Windows, switch to SelectorEventLoopPolicy (required for psycopg async)
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def is_ollama_running(url: str = "http://127.0.0.1:11434/api/tags") -> bool:
    """Check if the Ollama daemon is reachable on its API port."""
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def is_docker_daemon_running() -> bool:
    """Check if the Docker daemon is responding to CLI commands."""
    try:
        res = subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        return res.returncode == 0
    except Exception:
        return False


def are_docker_containers_up() -> bool:
    """Check if the docker-compose containers for this project are running."""
    try:
        res = subprocess.run(
            ["docker", "compose", "ps", "-q"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return res.returncode == 0 and bool(res.stdout.strip())
    except Exception:
        return False


def ensure_docker():
    """Ensure Docker Desktop is running and docker-compose containers are up."""
    logger.info("Checking Docker daemon status...")
    if not is_docker_daemon_running():
        logger.warning("Docker daemon is not responding. Attempting to start Docker Desktop...")
        # Common installation paths for Docker Desktop on Windows
        docker_paths = [
            r"C:\Program Files\Docker\Docker\Docker Desktop.exe",
            os.path.expandvars(r"%ProgramFiles%\Docker\Docker\Docker Desktop.exe")
        ]
        launched = False
        for path in docker_paths:
            if os.path.exists(path):
                subprocess.Popen([path], shell=False)
                launched = True
                logger.info(f"Launched Docker Desktop from: {path}")
                break

        if not launched:
            logger.warning("Docker Desktop executable not found in default location. Trying 'start docker'...")
            try:
                subprocess.Popen("start docker", shell=True)
            except Exception as e:
                logger.error(f"Failed to launch Docker: {e}")

        # Wait for daemon to become ready (up to 45 seconds)
        logger.info("Waiting for Docker daemon to become ready...")
        for attempt in range(45):
            time.sleep(2)
            if is_docker_daemon_running():
                logger.info("Docker daemon is now running and responsive.")
                break
        else:
            logger.warning("Docker daemon did not respond within timeout. Continuing anyway...")

    # Start project containers if docker is ready
    if is_docker_daemon_running():
        if not are_docker_containers_up():
            logger.info("Starting docker-compose containers (PostgreSQL, MinIO, Redis, ClamAV)...")
            try:
                subprocess.run(["docker", "compose", "up", "-d"], check=False)
            except Exception as e:
                logger.warning(f"Could not run 'docker compose up -d': {e}")
        else:
            logger.info("Docker containers are already running.")


def ensure_ollama():
    """Ensure Ollama daemon is running and responding."""
    logger.info("Checking Ollama service status...")
    if is_ollama_running():
        logger.info("Ollama is already running.")
        return

    logger.warning("Ollama is not running. Starting Ollama daemon...")
    ollama_bin = shutil.which("ollama")
    if not ollama_bin:
        # Fallback to standard Windows user path
        cand = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe")
        if os.path.exists(cand):
            ollama_bin = cand

    if ollama_bin:
        try:
            # Spawn ollama serve in background detached process
            if sys.platform == "win32":
                DETACHED_PROCESS = 0x00000008
                CREATE_NEW_PROCESS_GROUP = 0x00000200
                subprocess.Popen(
                    [ollama_bin, "serve"],
                    creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                    close_fds=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            else:
                subprocess.Popen([ollama_bin, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            logger.info(f"Spawned Ollama daemon ({ollama_bin} serve).")
        except Exception as e:
            logger.error(f"Failed to start Ollama daemon: {e}")
    else:
        logger.warning("Could not find ollama executable on system PATH or default installation directory.")

    # Wait for Ollama to become ready (up to 15 seconds)
    logger.info("Waiting for Ollama API to respond...")
    for _ in range(15):
        time.sleep(1)
        if is_ollama_running():
            logger.info("Ollama is now online and reachable at http://127.0.0.1:11434.")
            break
    else:
        logger.warning("Ollama did not respond within 15 seconds. Continuing anyway...")


def print_banner() -> None:
    """Print the service access banner so the user knows where everything is."""
    banner = """
╔══════════════════════════════════════════════════════════════════════╗
║              DOCINTAKE — SERVICE ACCESS LINKS                        ║
╠══════════════════════════════════════════════════════════════════════╣
║  Web UI             →  http://127.0.0.1:8000                         ║
║  PostgreSQL DB      →  postgresql://intake:***@localhost:5432/doc_intake ║
║  MinIO Storage API  →  http://127.0.0.1:9000                         ║
║  MinIO Web Console  →  http://127.0.0.1:9001                         ║
║    Bucket: onboarding-docs   User: minioadmin                        ║
║  Ollama API         →  http://127.0.0.1:11434                        ║
╚══════════════════════════════════════════════════════════════════════╝
"""
    print(banner, flush=True)


def run_server() -> None:
    """Ensure prerequisite services are running and start Uvicorn ASGI server."""
    ensure_docker()
    ensure_ollama()
    print_banner()

    import uvicorn
    from app.main import app
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )


if __name__ == "__main__":
    run_server()
