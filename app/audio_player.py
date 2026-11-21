from __future__ import annotations

import logging
from pathlib import Path


class AudioPlayer:
    """Best-effort, non-blocking audio playback for scanner notifications."""

    def __init__(
        self,
        audio_path: Path,
        enabled: bool,
        volume: float,
        logger: logging.Logger,
    ) -> None:
        self.logger = logger
        self._sound = None
        self._mixer = None

        if not enabled:
            self.logger.info("success_audio_disabled")
            return

        if not audio_path.exists():
            self.logger.warning("success_audio_file_not_found path=%s", audio_path)
            return

        try:
            import pygame

            pygame.mixer.init()
            self._mixer = pygame.mixer
            self._sound = pygame.mixer.Sound(str(audio_path))
            self._sound.set_volume(max(0.0, min(1.0, volume)))
            self.logger.info("success_audio_ready path=%s", audio_path)
        except Exception:
            self.logger.exception("success_audio_initialization_failed path=%s", audio_path)
            self._sound = None
            self._mixer = None

    def play(self) -> None:
        if self._sound is None:
            return

        try:
            self._sound.play()
        except Exception:
            self.logger.exception("success_audio_playback_failed")

    def close(self) -> None:
        if self._mixer is None:
            return

        try:
            self._mixer.quit()
        except Exception:
            self.logger.exception("success_audio_shutdown_failed")
