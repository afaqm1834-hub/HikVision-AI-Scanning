from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import requests

from app.utils.config import ApiConfig


class AttendanceApiClient:
    def __init__(self, config: ApiConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "x-api-key": self.config.api_key,
            }
        )

    def send_attendance(self, employee_id: int, camera_id: str) -> bool:
        payload = {
            "employee_id": employee_id,
            "camera_id": camera_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        url = f"{self.config.base_url.rstrip('/')}{self.config.attendance_path}"

        last_error: Exception | None = None
        for attempt in range(1, self.config.retry_attempts + 1):
            try:
                response = self.session.post(
                    url,
                    json=payload,
                    timeout=self.config.timeout_seconds,
                )
                if response.ok:
                    self.logger.info(
                        "attendance_posted employee_id=%s camera_id=%s status=%s",
                        employee_id,
                        camera_id,
                        response.status_code,
                    )
                    return True

                self.logger.warning(
                    "attendance_post_failed employee_id=%s camera_id=%s attempt=%s status=%s body=%s",
                    employee_id,
                    camera_id,
                    attempt,
                    response.status_code,
                    response.text[:300],
                )
            except requests.RequestException as exc:
                last_error = exc
                self.logger.warning(
                    "attendance_post_exception employee_id=%s camera_id=%s attempt=%s error=%s",
                    employee_id,
                    camera_id,
                    attempt,
                    exc,
                )

            if attempt < self.config.retry_attempts:
                time.sleep(self.config.retry_backoff_seconds * attempt)

        if last_error is not None:
            self.logger.error(
                "attendance_post_exhausted employee_id=%s camera_id=%s error=%s",
                employee_id,
                camera_id,
                last_error,
            )
        return False
