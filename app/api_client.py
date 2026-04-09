from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, request

from app.utils.config import ApiConfig


class AttendanceApiClient:
    def __init__(self, config: ApiConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger

    def send_attendance(self, employee_id: int, camera_id: str) -> bool:
        payload = json.dumps(
            {
                "employee_id": employee_id,
                "camera_id": camera_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ).encode("utf-8")
        url = f"{self.config.base_url.rstrip('/')}{self.config.attendance_path}"

        last_error: Exception | None = None
        for attempt in range(1, self.config.retry_attempts + 1):
            req = request.Request(
                url=url,
                data=payload,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": self.config.api_key,
                },
            )
            try:
                with request.urlopen(req, timeout=self.config.timeout_seconds) as response:
                    status = getattr(response, "status", 200)
                    if 200 <= status < 300:
                        self.logger.info(
                            "attendance_posted employee_id=%s camera_id=%s status=%s",
                            employee_id,
                            camera_id,
                            status,
                        )
                        return True

                    body = response.read().decode("utf-8", errors="replace")
                    self.logger.warning(
                        "attendance_post_failed employee_id=%s camera_id=%s attempt=%s status=%s body=%s",
                        employee_id,
                        camera_id,
                        attempt,
                        status,
                        body[:300],
                    )
            except error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                last_error = exc
                self.logger.warning(
                    "attendance_post_http_error employee_id=%s camera_id=%s attempt=%s status=%s body=%s",
                    employee_id,
                    camera_id,
                    attempt,
                    exc.code,
                    body[:300],
                )
            except error.URLError as exc:
                last_error = exc
                self.logger.warning(
                    "attendance_post_url_error employee_id=%s camera_id=%s attempt=%s error=%s",
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

    def fetch_enrollment_sync_data(self) -> dict | None:
        url = f"{self.config.base_url.rstrip('/')}{self.config.enrollment_sync_path}"
        req = request.Request(
            url=url,
            method="GET",
            headers={"x-api-key": self.config.api_key},
        )

        try:
            with request.urlopen(req, timeout=self.config.timeout_seconds) as response:
                payload = response.read().decode("utf-8")
                return json.loads(payload) if payload else {}
        except Exception as exc:
            self.logger.error("enrollment_sync_fetch_failed error=%s", exc)
            return None

    def report_enrollment_sync_status(self, results: list[dict]) -> bool:
        payload = json.dumps({"results": results}).encode("utf-8")
        url = f"{self.config.base_url.rstrip('/')}{self.config.enrollment_status_report_path}"
        req = request.Request(
            url=url,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.config.api_key,
            },
        )

        try:
            with request.urlopen(req, timeout=self.config.timeout_seconds) as response:
                status = getattr(response, "status", 200)
                if 200 <= status < 300:
                    self.logger.info(
                        "enrollment_sync_reported status=%s results=%s",
                        status,
                        len(results),
                    )
                    return True
        except Exception as exc:
            self.logger.error("enrollment_sync_report_failed error=%s", exc)

        return False

    def download_file(self, url: str, destination: Path) -> bool:
        destination.parent.mkdir(parents=True, exist_ok=True)
        req = request.Request(url=url, method="GET")

        try:
            with request.urlopen(req, timeout=self.config.timeout_seconds) as response:
                data = response.read()
                destination.write_bytes(data)
                return True
        except Exception as exc:
            self.logger.error(
                "enrollment_image_download_failed url=%s destination=%s error=%s",
                url,
                destination,
                exc,
            )
            return False
