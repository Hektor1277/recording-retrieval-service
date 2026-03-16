from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from importlib.resources import files
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.models.protocol import CreateJobRequest, HealthResponse
from app.services.orchestrator import JobOrchestrator, TERMINAL_JOB_STATUSES


def resolve_ui_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "app" / "ui"
    return Path(str(files("app").joinpath("ui")))


def create_app() -> FastAPI:
    app = FastAPI(title="Recording Retrieval Service", version="0.1.0")
    orchestrator = JobOrchestrator(log_dir=Path("logs"))
    app.state.orchestrator = orchestrator

    ui_root = resolve_ui_root()
    asset_root = ui_root / "assets"
    app.mount("/assets", StaticFiles(directory=str(asset_root)), name="assets")

    @app.get("/", response_class=FileResponse)
    async def index() -> FileResponse:
        return FileResponse(ui_root / "index.html")

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse()

    @app.post("/v1/jobs", status_code=202)
    async def create_job(request: CreateJobRequest) -> dict:
        accepted = orchestrator.create_job(request)
        return accepted.model_dump(by_alias=True)

    @app.get("/v1/jobs/{job_id}")
    async def get_job(job_id: str) -> dict:
        status = orchestrator.get_status(job_id)
        if status is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return status.model_dump(by_alias=True)

    @app.get("/v1/jobs/{job_id}/results")
    async def get_results(job_id: str) -> dict:
        status = orchestrator.get_status(job_id)
        if status is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if status.status not in TERMINAL_JOB_STATUSES:
            raise HTTPException(status_code=409, detail="Job is not finished yet")
        results = orchestrator.get_results(job_id)
        if results is None:
            raise HTTPException(status_code=409, detail="Job results are not ready")
        return results.model_dump(by_alias=True)

    @app.post("/v1/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str) -> dict:
        status = orchestrator.cancel_job(job_id)
        if status is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return status.model_dump(by_alias=True)

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Recording Retrieval Service")
    parser.add_argument("--mode", choices=["service", "ui"], default="service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4780)
    args = parser.parse_args()

    if args.mode == "ui":
        url = f"http://{args.host}:{args.port}/"
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    uvicorn.run(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
