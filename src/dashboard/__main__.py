"""python -m dashboard  -> serves the dashboard on port 8700 (needs uvicorn)."""
import os

try:
    import uvicorn
except ImportError as e:  # uvicorn is not in requirements-dev.txt yet
    raise SystemExit("uvicorn is not installed: pip install uvicorn, then rerun python -m dashboard") from e

uvicorn.run("dashboard.app:app", host="127.0.0.1", port=int(os.environ.get("DH_DASHBOARD_PORT", "8700")))
