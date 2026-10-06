from __future__ import annotations

import logging


logger = logging.getLogger("wiso-agent")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def log_event(request_id: str, event: str, **fields: object) -> None:
    safe = " ".join(f"{k}={v}" for k, v in fields.items() if v is not None)
    logger.info("request_id=%s event=%s %s", request_id, event, safe)
