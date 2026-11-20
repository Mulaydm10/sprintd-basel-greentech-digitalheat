"""Per-node FastAPI agent. TODO endpoints: /signal, /pause, /resume, /migrate, /status."""
from fastapi import FastAPI

app = FastAPI(title="digitalheat live agent")


@app.get("/status")
def status() -> dict:
    return {"ok": True}
