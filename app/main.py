from __future__ import annotations

import multiprocessing as mp
import signal
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.camera_worker import run_camera_worker
from app.api_client import AttendanceApiClient
from app.sync_service import EnrollmentSyncService
from app.mobile_attendance_worker import run_mobile_attendance_worker
from app.utils.config import CameraConfig
from app.utils.config import load_config
from app.utils.logging_utils import setup_logger


def _start_camera_processes(
    config,
    app_dir: Path,
    logger,
) -> list[mp.Process]:
    processes: list[mp.Process] = []
    for camera in config.cameras:
        process = mp.Process(
            target=run_camera_worker,
            args=(camera, config, str(app_dir)),
            name=f"camera-process-{camera.id}",
        )
        process.start()
        processes.append(process)
        logger.info("camera_process_started camera_id=%s pid=%s", camera.id, process.pid)
    return processes


def _stop_camera_processes(processes: list[mp.Process]) -> None:
    for process in processes:
        if process.is_alive():
            process.terminate()
    for process in processes:
        process.join(timeout=10)


def _start_mobile_process(config, app_dir: Path, logger):
    if not config.api.mobile_attendance_enabled:
        return None
    process = mp.Process(target=run_mobile_attendance_worker, args=(config, str(app_dir)), name="mobile-attendance-worker")
    process.start()
    logger.info("mobile_attendance_process_started pid=%s", process.pid)
    return process


def _start_sync_thread(config, app_dir: Path) -> tuple[EnrollmentSyncService, threading.Event, threading.Thread]:
    sync_service = EnrollmentSyncService(config=config, app_dir=app_dir)
    try:
        sync_service.run_once()
    except Exception:
        sync_service.logger.exception("initial_enrollment_sync_failed")

    sync_should_stop = threading.Event()
    sync_thread = threading.Thread(
        target=sync_service.run_forever,
        args=(sync_should_stop,),
        name="enrollment-sync-thread",
        daemon=True,
    )
    sync_thread.start()
    return sync_service, sync_should_stop, sync_thread


def _stop_sync_thread(sync_should_stop: threading.Event, sync_thread: threading.Thread) -> None:
    sync_should_stop.set()
    sync_thread.join(timeout=10)


def _fetch_remote_cameras(config, logger) -> list[CameraConfig] | None:
    client = AttendanceApiClient(config=config.api, logger=logger)
    payload = client.fetch_camera_config()
    if not payload:
        return None

    cameras_payload = payload.get("cameras") or []
    cameras: list[CameraConfig] = []
    for item in cameras_payload:
        try:
            cameras.append(CameraConfig(**item))
        except Exception:
            logger.exception("invalid_remote_camera_config_item item=%s", item)

    if not cameras:
        return None

    return cameras


def _camera_signature(cameras: list[CameraConfig]) -> tuple:
    return tuple(
        (
            camera.id,
            camera.label,
            camera.url,
            camera.vendor,
            camera.host,
            camera.port,
            camera.username,
            camera.password,
            camera.channel,
            camera.subtype,
            camera.use_custom_url,
            camera.custom_url,
        )
        for camera in cameras
    )


def main() -> int:
    app_dir = Path(__file__).resolve().parent
    config_path = app_dir / "config.yaml"
    config = load_config(config_path)
    logger = setup_logger(
        name="attendance_main",
        log_dir=str(app_dir / config.logging.log_dir),
        level=config.logging.level,
    )

    try:
        mp.set_start_method(config.runtime.process_start_method, force=True)
    except RuntimeError:
        logger.warning("multiprocessing_start_method_already_set")

    remote_cameras = _fetch_remote_cameras(config, logger)
    if remote_cameras:
        config = replace(config, cameras=remote_cameras)
        logger.info("remote_camera_config_loaded count=%s", len(remote_cameras))

    should_stop = mp.Event()
    config_mtime = config_path.stat().st_mtime if config_path.exists() else 0.0
    last_camera_poll = 0.0
    current_camera_signature = _camera_signature(config.cameras)

    def _handle_signal(signum: int, _frame: object) -> None:
        logger.warning("shutdown_signal_received signal=%s", signum)
        should_stop.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    _sync_service, sync_should_stop, sync_thread = _start_sync_thread(config, app_dir)
    processes = _start_camera_processes(config, app_dir, logger)
    mobile_process = _start_mobile_process(config, app_dir, logger)

    try:
        while not should_stop.is_set():
            should_reload = False
            current_mtime = config_path.stat().st_mtime if config_path.exists() else 0.0
            if current_mtime > config_mtime:
                logger.info("config_change_detected path=%s reloading_workers=true", config_path)
                config_mtime = current_mtime
                base_config = load_config(config_path)
                remote_cameras = _fetch_remote_cameras(base_config, logger)
                config = replace(base_config, cameras=remote_cameras or base_config.cameras)
                current_camera_signature = _camera_signature(config.cameras)
                should_reload = True

            now = time.time()
            if now - last_camera_poll >= config.api.camera_config_poll_interval_seconds:
                last_camera_poll = now
                remote_cameras = _fetch_remote_cameras(config, logger)
                if remote_cameras:
                    remote_signature = _camera_signature(remote_cameras)
                    if remote_signature != current_camera_signature:
                        logger.info("remote_camera_config_changed reloading_workers=true")
                        config = replace(config, cameras=remote_cameras)
                        current_camera_signature = remote_signature
                        should_reload = True

            if should_reload:
                _stop_sync_thread(sync_should_stop, sync_thread)
                _stop_camera_processes(processes)
                _stop_camera_processes([mobile_process] if mobile_process else [])
                _sync_service, sync_should_stop, sync_thread = _start_sync_thread(config, app_dir)
                processes = _start_camera_processes(config, app_dir, logger)
                mobile_process = _start_mobile_process(config, app_dir, logger)

            if mobile_process is not None and not mobile_process.is_alive():
                mobile_process.join(timeout=1)
                mobile_process = _start_mobile_process(config, app_dir, logger)

            for index, process in enumerate(processes):
                if process.is_alive():
                    continue

                if index >= len(config.cameras):
                    continue

                camera = config.cameras[index]
                logger.error(
                    "camera_process_stopped camera_id=%s exitcode=%s restarting",
                    camera.id,
                    process.exitcode,
                )
                replacement = mp.Process(
                    target=run_camera_worker,
                    args=(camera, config, str(app_dir)),
                    name=f"camera-process-{camera.id}",
                )
                replacement.start()
                processes[index] = replacement
                logger.info(
                    "camera_process_restarted camera_id=%s pid=%s",
                    camera.id,
                    replacement.pid,
                )
            time.sleep(config.runtime.queue_poll_interval_seconds)
    finally:
        _stop_sync_thread(sync_should_stop, sync_thread)
        _stop_camera_processes(processes)
        _stop_camera_processes([mobile_process] if mobile_process else [])
        logger.info("attendance_service_stopped")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
