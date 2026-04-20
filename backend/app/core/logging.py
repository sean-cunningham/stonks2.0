import logging


def configure_logging(log_level: str) -> None:
    """Configure process-wide logging once at startup."""
    root_logger = logging.getLogger()
    if root_logger.handlers:
        root_logger.setLevel(log_level.upper())
        return

    logging.basicConfig(
        level=log_level.upper(),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
