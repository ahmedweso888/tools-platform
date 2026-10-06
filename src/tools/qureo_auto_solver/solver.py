from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.tools.sprix_auto_solver.solver import SprixSolver


# ============================================================
# Configuration
# ============================================================

MAX_ACCOUNTS = int(os.getenv("MAX_ACCOUNTS", "5"))
JOB_TTL_SECONDS = int(os.getenv("JOB_TTL_SECONDS", "86400"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger("tools-platform")


# ============================================================
# App
# ============================================================

app = FastAPI(
    title="WISO Tools Platform",
    version="1.0.0",
)


allowed_origins_raw = os.getenv("ALLOWED_ORIGINS", "*").strip()

if allowed_origins_raw == "*":
    allowed_origins = ["*"]
else:
    allowed_origins = [
        origin.strip()
        for origin in allowed_origins_raw.split(",")
        if origin.strip()
    ]


app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=allowed_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# Models
# ============================================================

class Account(BaseModel):
    code: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=1, max_length=1024)


class SprixSolveRequest(BaseModel):
    accounts: list[Account] = Field(
        min_length=1,
        max_length=MAX_ACCOUNTS,
    )
    subject_id: str = Field(
        default="7",
        min_length=1,
        max_length=64,
    )


class QureoSolveRequest(BaseModel):
    accounts: list[Account] = Field(
        min_length=1,
        max_length=MAX_ACCOUNTS,
    )
    courses: list[str] = Field(
        default_factory=lambda: ["Python", "JavaScript"],
        max_length=20,
    )


class SubjectsRequest(Account):
    pass


# ============================================================
# Jobs
# ============================================================

jobs: dict[str, dict[str, Any]] = {}
jobs_lock = threading.Lock()

stop_events: dict[str, threading.Event] = {}

executor = ThreadPoolExecutor(
    max_workers=max(2, MAX_ACCOUNTS),
)


TERMINAL_STATUSES = {
    "completed",
    "completed_with_errors",
    "failed",
    "stopped",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_job(tool: str) -> str:
    request_id = str(uuid.uuid4())

    now = utc_now()

    with jobs_lock:
        jobs[request_id] = {
            "request_id": request_id,
            "status": "queued",
            "tool": tool,
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
            "results": [],
            "error": None,
        }

        stop_events[request_id] = threading.Event()

    return request_id


def update_job(request_id: str, **updates: Any) -> None:
    with jobs_lock:
        job = jobs.get(request_id)

        if not job:
            return

        job.update(
            {
                **updates,
                "updated_at": utc_now(),
            }
        )


def get_job(request_id: str) -> dict[str, Any] | None:
    with jobs_lock:
        job = jobs.get(request_id)

        if not job:
            return None

        return dict(job)


def finish_job(
    request_id: str,
    status: str,
    *,
    results: list[dict[str, Any]] | None = None,
    error: str | None = None,
) -> None:
    now = utc_now()

    with jobs_lock:
        job = jobs.get(request_id)

        if not job:
            return

        job["status"] = status
        job["updated_at"] = now
        job["completed_at"] = now

        if results is not None:
            job["results"] = results

        job["error"] = error


def should_stop(request_id: str) -> bool:
    with jobs_lock:
        event = stop_events.get(request_id)

    return event.is_set() if event else False


def cleanup_old_jobs() -> None:
    cutoff = time.time() - JOB_TTL_SECONDS

    with jobs_lock:
        remove_ids: list[str] = []

        for request_id, job in jobs.items():
            created_at = job.get("created_at")

            if not created_at:
                continue

            try:
                created_timestamp = datetime.fromisoformat(
                    created_at
                ).timestamp()
            except Exception:
                continue

            if created_timestamp < cutoff:
                remove_ids.append(request_id)

        for request_id in remove_ids:
            jobs.pop(request_id, None)
            stop_events.pop(request_id, None)


# ============================================================
# Safe error formatting
# ============================================================

def safe_error_message(exc: BaseException) -> str:
    """
    Return a useful runtime error without exposing credentials,
    stack traces, or huge internal payloads.
    """

    message = str(exc).strip()

    if not message:
        message = exc.__class__.__name__

    # Never return an enormous exception body to the client.
    message = message[:1000]

    # Basic credential redaction.
    lowered = message.lower()

    sensitive_words = (
        "password=",
        "password:",
        "passwd=",
        "token=",
        "authorization=",
        "bearer ",
    )

    if any(word in lowered for word in sensitive_words):
        return "Tool execution failed. Check the Railway logs for details."

    return message


# ============================================================
# SPRIX
# ============================================================

def _run_sprix(
    request_id: str,
    accounts: list[Account],
    subject_id: str,
) -> None:
    update_job(
        request_id,
        status="in_progress",
    )

    results: list[dict[str, Any]] = []

    try:
        for account in accounts:
            if should_stop(request_id):
                finish_job(
                    request_id,
                    "stopped",
                    results=results,
                )
                return

            try:
                solver = SprixSolver(
                    student_id=account.code,
                    password=account.password,
                )

                result = solver.run(
                    subject_id=subject_id,
                )

                results.append(
                    {
                        "code": account.code,
                        "success": True,
                        "result": result,
                    }
                )

            except Exception as exc:
                logger.exception(
                    "SPRIX account execution failed "
                    "request_id=%s code=%s",
                    request_id,
                    account.code,
                )

                results.append(
                    {
                        "code": account.code,
                        "success": False,
                        "error": safe_error_message(exc),
                    }
                )

        has_errors = any(
            item.get("success") is False
            for item in results
        )

        if should_stop(request_id):
            finish_job(
                request_id,
                "stopped",
                results=results,
            )
            return

        finish_job(
            request_id,
            "completed_with_errors" if has_errors else "completed",
            results=results,
        )

    except Exception as exc:
        logger.exception(
            "SPRIX job failed request_id=%s",
            request_id,
        )

        finish_job(
            request_id,
            "failed",
            results=results,
            error=safe_error_message(exc),
        )


# ============================================================
# QUREO
# ============================================================

def _run_qureo(
    request_id: str,
    accounts: list[Account],
    courses: list[str],
) -> None:
    update_job(
        request_id,
        status="in_progress",
    )

    results: list[dict[str, Any]] = []

    try:
        for account in accounts:
            if should_stop(request_id):
                finish_job(
                    request_id,
                    "stopped",
                    results=results,
                )
                return

            solver: QureoSolver | None = None

            try:
                logger.info(
                    "Starting Qureo solver "
                    "request_id=%s code=%s courses=%s",
                    request_id,
                    account.code,
                    courses,
                )

                solver = QureoSolver(
                    courses=courses,
                )

                result = solver.run(
                    student_id=account.code,
                    password=account.password,
                    courses=courses,
                )

                results.append(
                    {
                        "code": account.code,
                        "success": True,
                        "result": result,
                    }
                )

                logger.info(
                    "Qureo solver completed "
                    "request_id=%s code=%s",
                    request_id,
                    account.code,
                )

            except Exception as exc:
                error_message = safe_error_message(exc)

                logger.exception(
                    "Qureo execution failed "
                    "request_id=%s code=%s error=%s",
                    request_id,
                    account.code,
                    error_message,
                )

                # IMPORTANT:
                # Return the actual safe exception message to the WISO UI.
                results.append(
                    {
                        "code": account.code,
                        "success": False,
                        "error": error_message,
                    }
                )

            finally:
                # The solver normally owns its cleanup through run().
                # This block is intentionally defensive in case run()
                # fails before reaching its own cleanup.
                if solver is not None:
                    browser = getattr(solver, "browser", None)
                    playwright = getattr(solver, "playwright", None)

                    if browser is not None:
                        try:
                            browser.close()
                        except Exception:
                            logger.debug(
                                "Qureo browser cleanup failed",
                                exc_info=True,
                            )

                    if playwright is not None:
                        try:
                            playwright.stop()
                        except Exception:
                            logger.debug(
                                "Qureo Playwright cleanup failed",
                                exc_info=True,
                            )

        if should_stop(request_id):
            finish_job(
                request_id,
                "stopped",
                results=results,
            )
            return

        has_errors = any(
            item.get("success") is False
            for item in results
        )

        if has_errors:
            finish_job(
                request_id,
                "completed_with_errors",
                results=results,
            )
        else:
            finish_job(
                request_id,
                "completed",
                results=results,
            )

    except Exception as exc:
        logger.exception(
            "Qureo job failed request_id=%s",
            request_id,
        )

        finish_job(
            request_id,
            "failed",
            results=results,
            error=safe_error_message(exc),
        )


# ============================================================
# Health
# ============================================================

@app.get("/health")
def health() -> dict[str, Any]:
    cleanup_old_jobs()

    return {
        "status": "ok",
        "service": "wiso-tools-platform",
        "timestamp": utc_now(),
    }


@app.get("/health/tools")
def health_tools() -> dict[str, Any]:
    return {
        "status": "ok",
        "tools": {
            "sprix": True,
            "qureo": True,
        },
        "timestamp": utc_now(),
    }


# ============================================================
# SPRIX Subjects
# ============================================================

@app.post("/api/tools/sprix/subjects")
def sprix_subjects(payload: SubjectsRequest) -> dict[str, Any]:
    try:
        solver = SprixSolver(
            student_id=payload.code,
            password=payload.password,
        )

        subjects = solver.get_subjects()

        return {
            "success": True,
            "subjects": subjects,
        }

    except Exception as exc:
        logger.exception(
            "SPRIX subjects request failed code=%s",
            payload.code,
        )

        raise HTTPException(
            status_code=500,
            detail=safe_error_message(exc),
        ) from exc


# ============================================================
# Start SPRIX
# ============================================================

@app.post("/api/tools/sprix/solve")
def sprix_solve(payload: SprixSolveRequest) -> dict[str, Any]:
    cleanup_old_jobs()

    request_id = create_job("sprix")

    executor.submit(
        _run_sprix,
        request_id,
        payload.accounts,
        payload.subject_id,
    )

    return {
        "request_id": request_id,
        "status": "queued",
        "tool": "sprix",
    }


# ============================================================
# Start Qureo
# ============================================================

@app.post("/api/tools/qureo/solve")
def qureo_solve(payload: QureoSolveRequest) -> dict[str, Any]:
    cleanup_old_jobs()

    request_id = create_job("qureo")

    courses = payload.courses or [
        "Python",
        "JavaScript",
    ]

    executor.submit(
        _run_qureo,
        request_id,
        payload.accounts,
        courses,
    )

    return {
        "request_id": request_id,
        "status": "queued",
        "tool": "qureo",
    }


# ============================================================
# Job status
# ============================================================

@app.get("/api/jobs/{request_id}")
def job_status(request_id: str) -> dict[str, Any]:
    cleanup_old_jobs()

    job = get_job(request_id)

    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Job not found.",
        )

    return job


# ============================================================
# Stop job
# ============================================================

@app.post("/api/jobs/{request_id}/stop")
def stop_job(request_id: str) -> dict[str, Any]:
    cleanup_old_jobs()

    with jobs_lock:
        job = jobs.get(request_id)
        event = stop_events.get(request_id)

    if job is None or event is None:
        raise HTTPException(
            status_code=404,
            detail="Job not found.",
        )

    if job["status"] in TERMINAL_STATUSES:
        return {
            "success": True,
            "request_id": request_id,
            "status": job["status"],
        }

    event.set()

    update_job(
        request_id,
        status="stopping",
    )

    return {
        "success": True,
        "request_id": request_id,
        "status": "stopping",
    }


# ============================================================
# Cleanup on shutdown
# ============================================================

@app.on_event("shutdown")
def shutdown_event() -> None:
    logger.info("Shutting down tools platform.")

    executor.shutdown(
        wait=False,
        cancel_futures=True,
    )