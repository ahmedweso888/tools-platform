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

from src.shared.config import (
    ALLOWED_ORIGINS,
    JOB_TTL_SECONDS,
    LOG_LEVEL,
    MAX_ACCOUNTS,
    MAX_REQUEST_BYTES,
)

from src.tools.sprix_financial_literacy.solver import (
    Solver as SprixSolver,
    BankStore as SprixBankStore,
    list_subjects,
)


# ============================================================
# Logging
# ============================================================

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(message)s",
)

logger = logging.getLogger("tools-platform")


# ============================================================
# FastAPI
# ============================================================

app = FastAPI(
    title="Tools Platform",
    version="1.0.0",
)


if ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=[
            "Content-Type",
            "X-Request-ID",
            "Idempotency-Key",
        ],
    )


# ============================================================
# Executors
# ============================================================

# One executor handles complete jobs.
# A separate executor handles individual accounts.
#
# This avoids a deadlock where a job occupies all workers
# and then waits for account workers from the same pool.

job_executor = ThreadPoolExecutor(
    max_workers=max(2, MAX_ACCOUNTS),
)

account_executor = ThreadPoolExecutor(
    max_workers=max(1, MAX_ACCOUNTS),
)


# ============================================================
# Jobs
# ============================================================

jobs: dict[str, dict[str, Any]] = {}

jobs_lock = threading.Lock()


# ============================================================
# Models
# ============================================================

class Account(BaseModel):
    code: str = Field(
        min_length=1,
        max_length=256,
    )

    password: str = Field(
        min_length=1,
        max_length=1024,
    )


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
        default_factory=lambda: [
            "Python",
            "JavaScript",
        ],
        max_length=20,
    )


class SubjectsRequest(Account):
    pass


# ============================================================
# Helpers
# ============================================================

def _new_id(request: Request) -> str:
    return (
        request.headers.get("X-Request-ID")
        or str(uuid.uuid4())
    )


def _safe_error(exc: BaseException) -> str:
    """
    Return a useful error without exposing credentials,
    authorization headers, or stack traces.
    """

    message = str(exc).strip()

    if not message:
        message = exc.__class__.__name__

    message = message[:1000]

    lowered = message.lower()

    sensitive_markers = (
        "password=",
        "password:",
        "passwd=",
        "token=",
        "authorization=",
        "bearer ",
    )

    if any(marker in lowered for marker in sensitive_markers):
        return (
            "Tool execution failed. "
            "Check Railway logs for details."
        )

    return message


def _job_snapshot(job_id: str) -> dict[str, Any]:
    with jobs_lock:
        job = jobs.get(job_id)

        if not job:
            raise HTTPException(
                status_code=404,
                detail="job not found",
            )

        return {
            "request_id": job_id,
            "status": job["status"],
            "tool": job["tool"],
            "created_at": job["created_at"],
            "updated_at": job["updated_at"],
            "results": list(job["results"]),
            "error": job.get("error"),
        }


def _set_job(
    job_id: str,
    **updates: Any,
) -> None:
    with jobs_lock:
        job = jobs.get(job_id)

        if not job:
            return

        job.update(updates)
        job["updated_at"] = time.time()


def _start_job(
    job_id: str,
    tool: str,
    worker,
    count: int,
) -> None:
    now = time.time()

    with jobs_lock:
        jobs[job_id] = {
            "status": "in_progress",
            "tool": tool,
            "created_at": now,
            "updated_at": now,
            "results": [
                {
                    "index": i,
                    "status": "queued",
                }
                for i in range(count)
            ],
            "stop": threading.Event(),
            "error": None,
        }

    job_executor.submit(worker)


def _set_result(
    job_id: str,
    index: int,
    result: dict[str, Any],
) -> None:
    with jobs_lock:
        job = jobs.get(job_id)

        if not job:
            return

        job["results"][index] = {
            "index": index,
            **result,
        }

        job["updated_at"] = time.time()


def _finish_job(job_id: str) -> None:
    with jobs_lock:
        job = jobs.get(job_id)

        if not job:
            return

        statuses = [
            result.get("status")
            for result in job["results"]
        ]

        if any(
            status == "in_progress"
            for status in statuses
        ):
            return

        if all(
            status == "completed"
            for status in statuses
        ):
            job["status"] = "completed"

        elif any(
            status == "completed"
            for status in statuses
        ):
            job["status"] = "completed_with_errors"

        elif any(
            status == "stopped"
            for status in statuses
        ):
            job["status"] = "stopped"

        else:
            job["status"] = "failed"

        job["updated_at"] = time.time()


def _cleanup_jobs() -> None:
    cutoff = (
        time.time()
        - JOB_TTL_SECONDS
    )

    with jobs_lock:
        for job_id in list(jobs):
            if (
                jobs[job_id]["updated_at"]
                < cutoff
            ):
                jobs.pop(job_id, None)


# ============================================================
# SPRIX
# ============================================================

def _run_sprix(
    job_id: str,
    req: SprixSolveRequest,
) -> None:
    with jobs_lock:
        job = jobs.get(job_id)

    if not job:
        return

    stop_event = job["stop"]

    shared = SprixBankStore()
    shared.load(lambda *_: None)

    def run_one(
        index: int,
        account: Account,
    ) -> None:
        _set_result(
            job_id,
            index,
            {
                "status": "in_progress",
            },
        )

        def log(
            _msg,
            _level="info",
        ):
            # Do not persist solver logs.
            # This keeps credentials and user data
            # out of stored job results.
            return None

        try:
            if stop_event.is_set():
                _set_result(
                    job_id,
                    index,
                    {
                        "status": "stopped",
                    },
                )
                return

            solver = SprixSolver(
                log=log,
                stop=stop_event.is_set,
                shared=shared,
                subject_id=req.subject_id,
            )

            solver.on_progress = (
                lambda *_: None
            )

            ok, message = solver.run(
                account.code,
                account.password,
                subject=req.subject_id,
            )

            _set_result(
                job_id,
                index,
                {
                    "status": (
                        "completed"
                        if ok
                        else "failed"
                    ),
                    "success": bool(ok),
                    "message": (
                        message
                        if isinstance(message, str)
                        else "finished"
                    ),
                },
            )

        except Exception as exc:
            logger.exception(
                "SPRIX tool failed "
                "request_id=%s account_index=%s",
                job_id,
                index,
            )

            _set_result(
                job_id,
                index,
                {
                    "status": "failed",
                    "success": False,
                    "error": _safe_error(exc),
                },
            )

        finally:
            _finish_job(job_id)

    futures = [
        account_executor.submit(
            run_one,
            index,
            account,
        )
        for index, account in enumerate(
            req.accounts
        )
    ]

    for future in futures:
        future.result()

    _finish_job(job_id)


# ============================================================
# QUREO
# ============================================================

def _run_qureo(
    job_id: str,
    req: QureoSolveRequest,
) -> None:
    with jobs_lock:
        job = jobs.get(job_id)

    if not job:
        return

    stop_event = job["stop"]

    def run_one(
        index: int,
        account: Account,
    ) -> None:
        _set_result(
            job_id,
            index,
            {
                "status": "in_progress",
            },
        )

        solver = None

        try:
            if stop_event.is_set():
                _set_result(
                    job_id,
                    index,
                    {
                        "status": "stopped",
                    },
                )
                return

            # ==================================================
            # IMPORTANT:
            #
            # QureoSolver is intentionally imported HERE,
            # not at module level.
            #
            # This prevents the circular import that caused:
            #
            # ImportError:
            # cannot import name 'QureoSolver'
            # from partially initialized module
            # ==================================================

            from src.tools.qureo_auto_solver.solver import (
                QureoSolver,
            )

            import src.tools.qureo_auto_solver.solver as engine

            logger.info(
                "Starting Qureo solver "
                "request_id=%s account_index=%s courses=%s",
                job_id,
                index,
                req.courses,
            )

            solver = QureoSolver(
                headless=True,
                courses=req.courses,
            )

            # Allow the legacy engine to observe stop requests.
            engine.SHOULD_STOP = (
                stop_event.is_set
            )

            engine.PROGRESS = None

            result = solver.run(
                account.code,
                account.password,
                req.courses,
                close_pause=0,
            )

            if stop_event.is_set():
                _set_result(
                    job_id,
                    index,
                    {
                        "status": "stopped",
                        "success": False,
                    },
                )
                return

            _set_result(
                job_id,
                index,
                {
                    "status": "completed",
                    "success": True,
                    "result": result,
                },
            )

            logger.info(
                "Qureo solver completed "
                "request_id=%s account_index=%s",
                job_id,
                index,
            )

        except Exception as exc:
            error_message = _safe_error(exc)

            logger.exception(
                "Qureo tool failed "
                "request_id=%s account_index=%s error=%s",
                job_id,
                index,
                error_message,
            )

            # Return the real safe exception message
            # instead of the old generic:
            # "tool execution failed"
            _set_result(
                job_id,
                index,
                {
                    "status": "failed",
                    "success": False,
                    "error": error_message,
                },
            )

        finally:
            # Defensive cleanup.
            #
            # The legacy solver normally performs its own
            # cleanup inside run(), but this prevents a
            # partially initialized browser from surviving
            # if an exception happens before cleanup.

            if solver is not None:
                browser = getattr(
                    solver,
                    "browser",
                    None,
                )

                playwright = getattr(
                    solver,
                    "playwright",
                    None,
                )

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

            _finish_job(job_id)

    futures = [
        account_executor.submit(
            run_one,
            index,
            account,
        )
        for index, account in enumerate(
            req.accounts
        )
    ]

    for future in futures:
        future.result()

    _finish_job(job_id)


# ============================================================
# Request guard
# ============================================================

@app.middleware("http")
async def request_guard(
    request: Request,
    call_next,
):
    _cleanup_jobs()

    if request.method in {
        "POST",
        "PUT",
        "PATCH",
    }:
        try:
            length = int(
                request.headers.get(
                    "content-length",
                    "0",
                )
                or 0
            )
        except ValueError:
            length = 0

        if length > MAX_REQUEST_BYTES:
            raise HTTPException(
                status_code=413,
                detail="request too large",
            )

    response = await call_next(request)

    response.headers[
        "Cache-Control"
    ] = "no-store"

    return response


# ============================================================
# Health
# ============================================================

@app.get("/health")
def health():
    return {
        "status": "ok",
    }


@app.get("/health/tools")
def tools_health():
    return {
        "sprix_financial_literacy": "available",
        "qureo_auto_solver": "available",
    }


# ============================================================
# SPRIX subjects
# ============================================================

@app.post("/api/tools/sprix/subjects")
def sprix_subjects(
    payload: SubjectsRequest,
):
    try:
        subjects, error = list_subjects(
            payload.code,
            payload.password,
        )

        return {
            "success": error is None,
            "subjects": subjects,
            "error": error,
        }

    except Exception as exc:
        logger.exception(
            "SPRIX subjects failed"
        )

        return {
            "success": False,
            "subjects": [],
            "error": _safe_error(exc),
        }


# ============================================================
# Start SPRIX
# ============================================================

@app.post("/api/tools/sprix/solve")
def sprix_solve(
    request: Request,
    payload: SprixSolveRequest,
):
    job_id = _new_id(request)

    with jobs_lock:
        if job_id in jobs:
            return _job_snapshot(job_id)

    _start_job(
        job_id,
        "sprix_financial_literacy",
        lambda: _run_sprix(
            job_id,
            payload,
        ),
        len(payload.accounts),
    )

    return {
        "success": True,
        "request_id": job_id,
        "status": "in_progress",
    }


# ============================================================
# Start Qureo
# ============================================================

@app.post("/api/tools/qureo/solve")
def qureo_solve(
    request: Request,
    payload: QureoSolveRequest,
):
    job_id = _new_id(request)

    with jobs_lock:
        if job_id in jobs:
            return _job_snapshot(job_id)

    courses = payload.courses or [
        "Python",
        "JavaScript",
    ]

    payload = QureoSolveRequest(
        accounts=payload.accounts,
        courses=courses,
    )

    _start_job(
        job_id,
        "qureo_auto_solver",
        lambda: _run_qureo(
            job_id,
            payload,
        ),
        len(payload.accounts),
    )

    return {
        "success": True,
        "request_id": job_id,
        "status": "in_progress",
    }


# ============================================================
# Job status
# ============================================================

@app.get("/api/jobs/{request_id}")
def get_job(
    request_id: str,
):
    return _job_snapshot(request_id)


# ============================================================
# Stop
# ============================================================

@app.post("/api/jobs/{request_id}/stop")
def stop_job(
    request_id: str,
):
    with jobs_lock:
        job = jobs.get(request_id)

        if not job:
            raise HTTPException(
                status_code=404,
                detail="job not found",
            )

        job["stop"].set()
        job["updated_at"] = time.time()

    return {
        "success": True,
        "request_id": request_id,
        "status": "stopping",
    }


# ============================================================
# Root
# ============================================================

@app.get("/")
def root():
    return {
        "name": "tools-platform",
        "status": "ok",
        "health": "/health",
        "tools": [
            "/api/tools/sprix/solve",
            "/api/tools/qureo/solve",
        ],
    }


# ============================================================
# Shutdown
# ============================================================

@app.on_event("shutdown")
def shutdown_event():
    logger.info(
        "Shutting down tools platform."
    )

    job_executor.shutdown(
        wait=False,
        cancel_futures=True,
    )

    account_executor.shutdown(
        wait=False,
        cancel_futures=True,
    )