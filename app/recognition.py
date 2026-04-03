from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from insightface.app import FaceAnalysis

from app.utils.config import RecognitionConfig, RuntimeConfig


@dataclass(frozen=True)
class EmployeeRecord:
    employee_id: int
    name: str
    embeddings: np.ndarray


@dataclass(frozen=True)
class RecognitionResult:
    employee_id: int | None
    employee_name: str | None
    score: float
    accepted: bool
    reason: str


class FaceRecognitionEngine:
    def __init__(
        self,
        recognition_config: RecognitionConfig,
        runtime_config: RuntimeConfig,
        employees_path: str | Path,
        logger: logging.Logger,
    ) -> None:
        self.recognition_config = recognition_config
        self.runtime_config = runtime_config
        self.logger = logger
        self.employees = self._load_employees(employees_path)
        self.app = FaceAnalysis(
            name=self.runtime_config.detector_name,
            providers=self.runtime_config.providers,
        )
        self.app.prepare(ctx_id=0, det_size=(640, 640))

    def _load_employees(self, employees_path: str | Path) -> list[EmployeeRecord]:
        path = Path(employees_path)
        if not path.exists():
            self.logger.warning("employees_file_missing path=%s", path)
            return []

        with path.open("r", encoding="utf-8") as handle:
            payload: list[dict[str, Any]] = json.load(handle)

        employees: list[EmployeeRecord] = []
        for item in payload:
            embeddings = np.asarray(item["embeddings"], dtype=np.float32)
            if embeddings.ndim != 2 or embeddings.shape[0] == 0:
                self.logger.warning(
                    "invalid_employee_embeddings employee_id=%s name=%s",
                    item.get("employee_id"),
                    item.get("name"),
                )
                continue

            normalized = self._normalize_matrix(embeddings)
            employees.append(
                EmployeeRecord(
                    employee_id=int(item["employee_id"]),
                    name=str(item["name"]),
                    embeddings=normalized,
                )
            )

        self.logger.info("loaded_employees count=%s", len(employees))
        return employees

    def detect_faces(self, frame: np.ndarray) -> list[dict[str, Any]]:
        return self.app.get(frame)

    def evaluate_face(
        self,
        face: dict[str, Any],
        frame: np.ndarray,
    ) -> RecognitionResult:
        bbox = np.asarray(face["bbox"], dtype=np.int32)
        left, top, right, bottom = bbox.tolist()
        width = max(0, right - left)
        height = max(0, bottom - top)

        if min(width, height) < self.recognition_config.face_min_size:
            return RecognitionResult(None, None, 0.0, False, "face_too_small")

        crop = frame[max(0, top):max(0, bottom), max(0, left):max(0, right)]
        if crop.size == 0:
            return RecognitionResult(None, None, 0.0, False, "empty_crop")

        blur_score = cv2.Laplacian(
            cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), cv2.CV_64F
        ).var()
        if blur_score < self.recognition_config.blur_threshold:
            return RecognitionResult(None, None, 0.0, False, "face_too_blurry")

        embedding = np.asarray(face.get("embedding"), dtype=np.float32)
        if embedding.size == 0:
            return RecognitionResult(None, None, 0.0, False, "missing_embedding")

        normalized_embedding = self._normalize_vector(embedding)
        best_match = self._match_employee(normalized_embedding)
        if best_match is None:
            return RecognitionResult(None, None, 0.0, False, "no_employees_loaded")

        employee, score = best_match
        if score < self.recognition_config.threshold:
            return RecognitionResult(None, None, float(score), False, "below_threshold")

        return RecognitionResult(
            employee_id=employee.employee_id,
            employee_name=employee.name,
            score=float(score),
            accepted=True,
            reason="matched",
        )

    def _match_employee(
        self, embedding: np.ndarray
    ) -> tuple[EmployeeRecord, float] | None:
        if not self.employees:
            return None

        scored: list[tuple[EmployeeRecord, float]] = []
        for employee in self.employees:
            similarities = employee.embeddings @ embedding
            if self.recognition_config.match_strategy == "best_match":
                score = float(np.max(similarities))
            else:
                top_k = min(self.recognition_config.top_k, similarities.shape[0])
                top_values = np.sort(similarities)[-top_k:]
                score = float(np.mean(top_values))
            scored.append((employee, score))

        return max(scored, key=lambda item: item[1])

    @staticmethod
    def _normalize_vector(vector: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(vector)
        if norm == 0:
            return vector
        return vector / norm

    @classmethod
    def _normalize_matrix(cls, matrix: np.ndarray) -> np.ndarray:
        rows = [cls._normalize_vector(row) for row in matrix]
        return np.asarray(rows, dtype=np.float32)
