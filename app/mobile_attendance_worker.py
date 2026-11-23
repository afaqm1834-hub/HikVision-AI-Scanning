from __future__ import annotations

import time
from pathlib import Path
from uuid import UUID

from app.api_client import AttendanceApiClient
from app.recognition import FaceRecognitionEngine
from app.utils.logging_utils import setup_logger


class MobileAttendanceWorker:
    def __init__(self, config, app_dir: Path):
        self.config = config
        self.app_dir = app_dir
        self.logger = setup_logger("mobile_attendance", str(app_dir / config.logging.log_dir), config.logging.level)
        self.client = AttendanceApiClient(config.api, self.logger)
        self.engine = None
        self.pending_result = None

    def run_once(self) -> bool:
        if self.pending_result is None:
            payload = self.client.mobile_json("/api/mobile/attendance/worker/claim", {})
            job = (payload or {}).get("job")
            if not job:
                return False
            request_id = str(UUID(job["request_id"]))
            lease_token = job["lease_token"]
            result = {"outcome": "error", "reason": "VERIFICATION_ERROR"}
            try:
                image = self.client.mobile_photo(request_id, lease_token)
                if image:
                    if self.engine is None:
                        self.engine = FaceRecognitionEngine(
                            self.config.recognition, self.config.runtime,
                            self.app_dir / "employees.json", self.logger,
                        )
                    result = self.engine.verify_mobile_photo(image, int(job["employee_id"]))
            except Exception:
                self.logger.exception("mobile_verification_failed request_id=%s", request_id)
            self.pending_result = (request_id, {**result, "lease_token": lease_token})
        request_id, result = self.pending_result
        response = self.client.mobile_json(f"/api/mobile/attendance/worker/jobs/{request_id}/result", result)
        if response and (response.get("request") or response.get("http_status") in {400, 404, 409}):
            self.logger.info("mobile_verification_reported request_id=%s outcome=%s", request_id, result["outcome"])
            self.pending_result = None
        return True


def run_mobile_attendance_worker(config, app_dir: str) -> None:
    worker = MobileAttendanceWorker(config, Path(app_dir))
    while True:
        try:
            worker.run_once()
        except Exception:
            worker.logger.exception("mobile_attendance_worker_cycle_failed")
        time.sleep(max(0.5, float(config.api.mobile_attendance_poll_seconds)))
