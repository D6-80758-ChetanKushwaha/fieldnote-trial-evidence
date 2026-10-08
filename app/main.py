"""FastAPI routes and browser UI for the trial evidence catalog."""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.agent import agent_is_configured, ask_agent, stream_agent
from app.catalog import TrialCatalog


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "demo-data" if (ROOT / "demo-data").is_dir() else ROOT / "sample-data"
DATA_DIR = Path(os.getenv("TRIAL_DATA_DIR", str(DEFAULT_DATA_DIR))).resolve()
catalog = TrialCatalog(DATA_DIR)
app = FastAPI(title="Agricultural Trial Evidence", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip().rstrip("/")
        for origin in os.getenv(
            "CORS_ORIGINS", "https://d6-80758-chetankushwaha.github.io"
        ).split(",")
        if origin.strip()
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Accept"],
)
app.mount("/static", StaticFiles(directory=ROOT / "app" / "static"), name="static")


class QuestionRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)


class CompareRequest(BaseModel):
    trial_ids: list[str] = Field(min_length=1, max_length=30)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(ROOT / "app" / "static" / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "trial_count": len(catalog.trials), "agent_configured": agent_is_configured()}


@app.get("/api/facets")
def facets() -> dict:
    return catalog.facets()


@app.get("/api/trials")
def search_trials(
    trial_id: str | None = None, crop: str | None = None,
    product: str | None = None, country: str | None = None,
    year_from: int | None = Query(default=None, ge=1900, le=2200),
    year_to: int | None = Query(default=None, ge=1900, le=2200),
    trial_type: str | None = None,
) -> dict:
    trials = catalog.search(trial_id=trial_id, crop=crop, product=product, country=country,
                            year_from=year_from, year_to=year_to, trial_type=trial_type)
    return {"count": len(trials), "trials": trials}


@app.get("/api/trials/{trial_id}")
def get_trial(trial_id: str) -> dict:
    trial = catalog.trials.get(trial_id.upper())
    if trial is None:
        raise HTTPException(status_code=404, detail="Trial not found")
    return trial


@app.post("/api/compare")
def compare(request: CompareRequest) -> dict:
    ids = list(dict.fromkeys(trial_id.upper() for trial_id in request.trial_ids))
    missing = [trial_id for trial_id in ids if trial_id not in catalog.trials]
    if missing:
        raise HTTPException(status_code=404, detail=f"Unknown trials: {', '.join(missing)}")
    return {"trials": [catalog.trials[trial_id] for trial_id in ids]}


@app.get("/api/sources/{source_name}", response_class=PlainTextResponse)
def source(source_name: str) -> str:
    content = catalog.source_text(source_name)
    if content is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return content


@app.post("/api/agent/ask")
def agent_ask(request: QuestionRequest) -> dict:
    return ask_agent(catalog, request.question)


@app.post("/api/agent/stream")
def agent_stream(request: QuestionRequest) -> StreamingResponse:
    def events():
        for event in stream_agent(catalog, request.question):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
