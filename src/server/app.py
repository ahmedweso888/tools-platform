from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.shared.config import ALLOWED_ORIGINS, MAX_ACCOUNTS, MAX_REQUEST_BYTES, JOB_TTL_SECONDS, LOG_LEVEL
from src.tools.sprix_financial_literacy.solver import Solver as SprixSolver, BankStore as SprixBankStore, list_subjects
from src.tools.qureo_auto_solver.solver import QureoSolver

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("tools-platform")

app = FastAPI(title="Tools Platform", version="1.0.0")
if ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Request-ID", "Idempotency-Key"],
    )

executor = ThreadPoolExecutor(max_workers=MAX_ACCOUNTS)
jobs: dict[str, dict[str, Any]] = {}
jobs_lock = threading.Lock()


class Account(BaseModel):
    code: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=1, max_length=1024)


class SprixSolveRequest(BaseModel):
    accounts: list[Account] = Field(min_length=1, max_length=MAX_ACCOUNTS)
    subject_id: str = Field(default="7", min_length=1, max_length=64)


class QureoSolveRequest(BaseModel):
    accounts: list[Account] = Field(min_length=1, max_length=MAX_ACCOUNTS)
    courses: list[str] = Field(default_factory=lambda: ["Python", "JavaScript"], max_length=20)


class SubjectsRequest(Account):
    pass


def _new_id(request: Request) -> str:
    return request.headers.get("X-Request-ID") or str(uuid.uuid4())


def _job_snapshot(job_id: str) -> dict[str, Any]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return {
            "request_id": job_id,
            "status": job["status"],
            "tool": job["tool"],
            "created_at": job["created_at"],
            "updated_at": job["updated_at"],
            "results": list(job["results"]),
            "error": job.get("error"),
        }


def _set_job(job_id: str, **updates: Any) -> None:
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id].update(updates)
            jobs[job_id]["updated_at"] = time.time()


def _start_job(job_id: str, tool: str, worker, count: int) -> None:
    with jobs_lock:
        jobs[job_id] = {
            "status": "in_progress",
            "tool": tool,
            "created_at": time.time(),
            "updated_at": time.time(),
            "results": [{"index": i, "status": "queued"} for i in range(count)],
            "stop": threading.Event(),
            "error": None,
        }
    executor.submit(worker)


def _set_result(job_id: str, index: int, result: dict[str, Any]) -> None:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return
        job["results"][index] = {"index": index, **result}
        job["updated_at"] = time.time()


def _finish_job(job_id: str) -> None:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return
        statuses = [r.get("status") for r in job["results"]]
        if any(s == "in_progress" for s in statuses):
            return
        if all(s == "completed" for s in statuses):
            job["status"] = "completed"
        elif any(s == "completed" for s in statuses):
            job["status"] = "completed_with_errors"
        elif any(s == "stopped" for s in statuses):
            job["status"] = "stopped"
        else:
            job["status"] = "failed"
        job["updated_at"] = time.time()


def _cleanup_jobs() -> None:
    cutoff = time.time() - JOB_TTL_SECONDS
    with jobs_lock:
        for jid in list(jobs):
            if jobs[jid]["updated_at"] < cutoff:
                jobs.pop(jid, None)


def _run_sprix(job_id: str, req: SprixSolveRequest) -> None:
    stop_event = jobs[job_id]["stop"]
    shared = SprixBankStore()
    shared.load(lambda *_: None)

    def run_one(index: int, account: Account) -> None:
        _set_result(job_id, index, {"status": "in_progress"})
        def log(_msg, _level="info"):
            # Deliberately do not persist solver logs; credentials and user input stay out of logs.
            return None
        try:
            if stop_event.is_set():
                _set_result(job_id, index, {"status": "stopped"})
                return
            solver = SprixSolver(log=log, stop=stop_event.is_set, shared=shared, subject_id=req.subject_id)
            solver.on_progress = lambda *_: None
            ok, message = solver.run(account.code, account.password, subject=req.subject_id)
            _set_result(job_id, index, {
                "status": "completed" if ok else "failed",
                "success": bool(ok),
                "message": message if isinstance(message, str) else "finished",
            })
        except Exception:
            logger.exception("sprix tool failed request_id=%s account_index=%s", job_id, index)
            _set_result(job_id, index, {"status": "failed", "success": False, "message": "tool execution failed"})
        finally:
            _finish_job(job_id)

    futures = [executor.submit(run_one, i, a) for i, a in enumerate(req.accounts)]
    for f in futures:
        f.result()
    _finish_job(job_id)


def _run_qureo(job_id: str, req: QureoSolveRequest) -> None:
    stop_event = jobs[job_id]["stop"]

    def run_one(index: int, account: Account) -> None:
        _set_result(job_id, index, {"status": "in_progress"})
        try:
            if stop_event.is_set():
                _set_result(job_id, index, {"status": "stopped"})
                return
            solver = QureoSolver(headless=True, courses=req.courses)
            # The legacy engine checks this callback between long-running steps.
            import src.tools.qureo_auto_solver.solver as engine
            engine.SHOULD_STOP = stop_event.is_set
            engine.PROGRESS = None
            solver.run(account.code, account.password, req.courses, close_pause=0)
            _set_result(job_id, index, {"status": "completed", "success": True})
        except Exception:
            logger.exception("qureo tool failed request_id=%s account_index=%s", job_id, index)
            _set_result(job_id, index, {"status": "failed", "success": False, "message": "tool execution failed"})
        finally:
            _finish_job(job_id)

    futures = [executor.submit(run_one, i, a) for i, a in enumerate(req.accounts)]
    for f in futures:
        f.result()
    _finish_job(job_id)


@app.middleware("http")
async def request_guard(request: Request, call_next):
    _cleanup_jobs()
    if request.method in {"POST", "PUT", "PATCH"}:
        length = int(request.headers.get("content-length", "0") or 0)
        if length > MAX_REQUEST_BYTES:
            raise HTTPException(status_code=413, detail="request too large")
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/tools")
def tools_health():
    return {
        "sprix_financial_literacy": "available",
        "qureo_auto_solver": "available",
    }


@app.post("/api/tools/sprix/subjects")
def sprix_subjects(payload: SubjectsRequest):
    try:
        subjects, error = list_subjects(payload.code, payload.password)
        return {"success": error is None, "subjects": subjects, "error": error}
    except Exception:
        logger.exception("sprix subjects failed")
        return {"success": False, "subjects": [], "error": "tool execution failed"}


@app.post("/api/tools/sprix/solve")
def sprix_solve(request: Request, payload: SprixSolveRequest):
    job_id = _new_id(request)
    with jobs_lock:
        if job_id in jobs:
            return _job_snapshot(job_id)
    _start_job(job_id, "sprix_financial_literacy", lambda: _run_sprix(job_id, payload), len(payload.accounts))
    return {"success": True, "request_id": job_id, "status": "in_progress"}


@app.post("/api/tools/qureo/solve")
def qureo_solve(request: Request, payload: QureoSolveRequest):
    job_id = _new_id(request)
    with jobs_lock:
        if job_id in jobs:
            return _job_snapshot(job_id)
    _start_job(job_id, "qureo_auto_solver", lambda: _run_qureo(job_id, payload), len(payload.accounts))
    return {"success": True, "request_id": job_id, "status": "in_progress"}


@app.get("/api/jobs/{request_id}")
def get_job(request_id: str):
    return _job_snapshot(request_id)


@app.post("/api/jobs/{request_id}/stop")
def stop_job(request_id: str):
    with jobs_lock:
        job = jobs.get(request_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        job["stop"].set()
        job["updated_at"] = time.time()
    return {"success": True, "request_id": request_id, "status": "stopping"}


@app.get("/")
def root():
    return {
        "name": "tools-platform",
        "status": "ok",
        "health": "/health",
        "tools": ["/api/tools/sprix/solve", "/api/tools/qureo/solve"],
    }
