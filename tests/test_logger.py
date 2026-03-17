import os
import tempfile
import logging

from lailabot.logger import setup_logger


def test_logger_creates_log_file_and_writes():
    with tempfile.TemporaryDirectory() as tmp:
        logger = setup_logger(log_dir=tmp)
        logger.info("test message")

        log_files = [f for f in os.listdir(tmp) if f.endswith(".log")]
        assert len(log_files) >= 1

        with open(os.path.join(tmp, log_files[0])) as f:
            content = f.read()
        assert "test message" in content


def test_logger_rotates_on_size():
    with tempfile.TemporaryDirectory() as tmp:
        # Very small max_bytes to force rotation
        logger = setup_logger(log_dir=tmp, max_bytes=100, backup_count=3)
        for i in range(50):
            logger.info(f"message number {i} with some padding to fill up space")

        log_files = [f for f in os.listdir(tmp)]
        # Should have created backup files
        assert len(log_files) > 1
