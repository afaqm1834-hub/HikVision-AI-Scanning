import logging
import io
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from app.recognition import EmployeeRecord, FaceRecognitionEngine, RecognitionResult
from app.mobile_attendance_worker import MobileAttendanceWorker


class MobileFaceTests(unittest.TestCase):
    def engine(self):
        engine = FaceRecognitionEngine.__new__(FaceRecognitionEngine)
        engine.recognition_config = SimpleNamespace(threshold=0.55, match_strategy="top3_average", top_k=3)
        engine.employees = [EmployeeRecord(7, "Employee", np.array([[1., 0.]], dtype=np.float32)),
                            EmployeeRecord(8, "Other", np.array([[0., 1.]], dtype=np.float32))]
        engine.reload_employees_if_changed = Mock(return_value=False)
        return engine

    def test_matching_checks_claimed_employee_instead_of_returning_another_employee(self):
        engine = self.engine()
        employee, score = engine._match_employee(np.array([0., 1.], dtype=np.float32), employee_id=7)
        self.assertEqual(employee.employee_id, 7)
        self.assertEqual(score, 0)

    def test_missing_enrollment_is_explicit(self):
        self.assertEqual(self.engine().verify_mobile_photo(b"invalid", 99)["reason"], "EMPLOYEE_NOT_ENROLLED")

    def test_corrupt_image_never_matches(self):
        self.assertEqual(self.engine().verify_mobile_photo(b"invalid", 7)["reason"], "INVALID_PHOTO")

    def test_photo_needs_exactly_one_face_and_uses_the_employee_id(self):
        engine = self.engine()
        _, image = cv2.imencode(".jpg", np.zeros((100, 100, 3), dtype=np.uint8))
        engine.detect_faces = Mock(return_value=[])
        self.assertEqual(engine.verify_mobile_photo(image.tobytes(), 7)["reason"], "NO_FACE")
        engine.detect_faces.return_value = [{}, {}]
        self.assertEqual(engine.verify_mobile_photo(image.tobytes(), 7)["reason"], "MULTIPLE_FACES")
        engine.detect_faces.return_value = [{}]
        engine.evaluate_face = Mock(return_value=RecognitionResult(7, "Employee", 0.8, True, "matched"))
        self.assertEqual(engine.verify_mobile_photo(image.tobytes(), 7)["outcome"], "matched")
        self.assertEqual(engine.evaluate_face.call_args.kwargs["employee_id"], 7)

    def test_failed_embedding_reload_is_retried_after_a_partial_file(self):
        engine = self.engine()
        with patch("app.recognition.Path") as path_class:
            stored_file = path_class.return_value
            stored_file.exists.return_value = True
            stored_file.stat.return_value.st_mtime = 99
            stored_file.open.return_value.__enter__.return_value = io.StringIO("[")
            engine.employees_path = Path("employees.json")
            engine.logger = logging.getLogger("test")
            engine._employees_mtime = 0
            engine.employees_path.write_text("[", encoding="utf-8")
            with self.assertRaises(ValueError):
                FaceRecognitionEngine._load_employees(engine, engine.employees_path)
            self.assertEqual(engine._employees_mtime, 0)

    def test_worker_retries_reporting_without_reverifying_or_claiming_another_job(self):
        worker = MobileAttendanceWorker.__new__(MobileAttendanceWorker)
        worker.logger = logging.getLogger("test")
        worker.pending_result = None
        worker.engine = Mock()
        worker.engine.verify_mobile_photo.return_value = {"outcome": "matched", "score": 0.8, "threshold": 0.55}
        worker.client = Mock()
        worker.client.mobile_photo.return_value = b"photo"
        worker.client.mobile_json.side_effect = [
            {"job": {"request_id": "f16be35e-4cbb-471a-a9ca-ebd455d37af2", "employee_id": "7", "lease_token": "token"}},
            None, {"request": {"status": "marked"}},
        ]
        worker.run_once(); self.assertIsNotNone(worker.pending_result)
        worker.run_once(); self.assertIsNone(worker.pending_result)
        worker.engine.verify_mobile_photo.assert_called_once_with(b"photo", 7)


if __name__ == "__main__":
    unittest.main()
