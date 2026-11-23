from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CameraConfig:
    id: str
    url: str
    label: str | None = None
    vendor: str | None = None
    host: str | None = None
    port: int | None = None
    username: str | None = None
    password: str | None = None
    channel: int | None = None
    subtype: str | None = None
    use_custom_url: bool = False
    custom_url: str | None = None


@dataclass(frozen=True)
class RecognitionConfig:
    threshold: float
    cooldown_seconds: int
    min_frames: int
    process_every_n_frames: int
    face_min_size: int
    blur_threshold: float
    resize_width: int
    match_strategy: str
    top_k: int
    unknown_save_limit_per_hour: int


@dataclass(frozen=True)
class RuntimeConfig:
    reconnect_delay_seconds: int
    queue_poll_interval_seconds: float
    process_start_method: str
    providers: list[str]
    scrfd_model_path: str
    arcface_model_path: str
    detector_input_width: int
    detector_input_height: int
    detector_score_threshold: float
    detector_nms_threshold: float


@dataclass(frozen=True)
class ApiConfig:
    base_url: str
    attendance_path: str
    api_key: str
    timeout_seconds: int
    retry_attempts: int
    retry_backoff_seconds: float
    employees_sync_path: str = "/api/face-attendance/employees"
    camera_config_path: str = "/api/face-attendance/camera-config"
    enrollment_sync_path: str = "/api/face-enrollment/sync"
    enrollment_status_report_path: str = "/api/face-enrollment/sync/report"
    unknown_person_detect_path: str = "/api/unknown-persons/detect"
    unknown_persons_sync_path: str = "/api/unknown-persons/sync"
    sync_poll_interval_seconds: int = 120
    camera_config_poll_interval_seconds: int = 30
    enrollment_dataset_dir: str = "synced-enrollments"
    mobile_attendance_enabled: bool = True
    mobile_attendance_poll_seconds: float = 2.0


@dataclass(frozen=True)
class LoggingConfig:
    log_dir: str
    unknown_faces_dir: str
    level: str


@dataclass(frozen=True)
class AudioConfig:
    enabled: bool
    success_sound_path: str
    volume: float


@dataclass(frozen=True)
class AppConfig:
    cameras: list[CameraConfig]
    recognition: RecognitionConfig
    runtime: RuntimeConfig
    api: ApiConfig
    logging: LoggingConfig
    audio: AudioConfig


def load_config(config_path: str | Path) -> AppConfig:
    with Path(config_path).open("r", encoding="utf-8") as handle:
        payload: dict[str, Any] = json.load(handle)

    return AppConfig(
        cameras=[CameraConfig(**camera) for camera in payload["cameras"]],
        recognition=RecognitionConfig(**payload["recognition"]),
        runtime=RuntimeConfig(**payload["runtime"]),
        api=ApiConfig(**payload["api"]),
        logging=LoggingConfig(**payload["logging"]),
        audio=AudioConfig(**payload.get("audio", {
            "enabled": True,
            "success_sound_path": "audio/att-sound.mp3",
            "volume": 1.0,
        })),
    )
