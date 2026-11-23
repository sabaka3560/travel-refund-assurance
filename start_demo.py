"""Start or reuse the local demo, checking its Python dependencies first."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parent
URL = "http://127.0.0.1:8000"


def health():
    try:
        with urllib.request.urlopen(URL + "/api/health", timeout=2) as response:
            data = json.load(response)
        return data if data.get("ok") and data.get("engine_version") else None
    except (OSError, ValueError, urllib.error.URLError):
        return None


def main():
    if sys.version_info < (3, 10):
        raise RuntimeError("Use Python 3.10 or newer (the verified demo uses Python 3.12).")
    missing = []
    for module in ["fastapi", "uvicorn", "multipart", "pydantic", "google.generativeai"]:
        try:
            if importlib.util.find_spec(module) is None:
                missing.append(module)
        except ModuleNotFoundError:
            missing.append(module)
    try:
        ZoneInfo("Asia/Kolkata")
    except ZoneInfoNotFoundError:
        missing.append("tzdata")
    if missing:
        raise RuntimeError("Missing: " + ", ".join(missing) + '\nInstall with: python -m pip install -r "' + str(ROOT / "server" / "requirements.txt") + '"')

    current = health()
    if not current:
        if "--check" in sys.argv:
            raise RuntimeError("Server is not healthy. Run start-demo.cmd to start it.")
        # Import validates corpus and dependencies before detaching the process.
        sys.path.insert(0, str(ROOT / "server"))
        import app
        if not app.gemini_key():
            raise RuntimeError("GEMINI_API_KEY is missing. Configure it before the upload demo.")
        with (ROOT / "server" / "server.stdout.log").open("a") as out, (ROOT / "server" / "server.stderr.log").open("a") as err:
            process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8000"],
                cwd=ROOT / "server", stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS) if sys.platform == "win32" else 0,
                start_new_session=sys.platform != "win32",
            )
        for _ in range(60):
            if process.poll() is not None:
                raise RuntimeError("Server could not start. See server/server.stderr.log; port 8000 may already be occupied.")
            current = health()
            if current:
                (ROOT / "server" / "server.pid").write_text(str(process.pid), encoding="ascii")
                print("Started demo server (PID " + str(process.pid) + ").")
                break
            time.sleep(0.25)
        if not current:
            raise RuntimeError("Startup did not complete. See server/server.stderr.log.")
    if not current.get("api_key_set"):
        raise RuntimeError("Server is running but document extraction has no Gemini API key.")
    print("Demo ready at " + URL)
    print("Python dependencies: OK | Document extraction: configured")
    print("Engine " + current["engine_version"] + " | Corpus " + current["corpus_version"])
    print("Policy copies verified: " + current["evidence_verified"] + " | Quarantined rules: " + str(current["quarantined_rules"]))
    print("No separate database, Redis, or frontend server is required.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Demo startup: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
