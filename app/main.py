from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routers import faelle, laeufe, pruefen, system
from config import RUNS_DIR, STATIC_DIR

app = FastAPI(title="Begutachtung")

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Seitenbilder werden bewusst NICHT als StaticFiles gemountet: der
# Zwischenspeicher enthaelt Seiten aus Patientenakten, und ein Mount waere ein
# Pfad-Traversal-Risiko darauf. Sie kommen ueber eine geprüfte Route in
# app/routers/pruefen.py.

RUNS_DIR.mkdir(parents=True, exist_ok=True)

app.include_router(faelle.router)
app.include_router(laeufe.router)
app.include_router(pruefen.router)
app.include_router(system.router)
