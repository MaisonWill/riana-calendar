"""Network layer for downloading Airbnb iCal feeds."""

from __future__ import annotations

import logging
import time

import httpx

from src.config import PropertyConfig

LOGGER = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def fetch_ical(url: str, timeout: int = 30) -> str:
    """Download a single .ics payload with retry.

    Args:
        url: Airbnb iCal URL.
        timeout: Request timeout in seconds.

    Returns:
        Raw iCal content.

    Raises:
        RuntimeError: If all retries fail.
    """
    max_attempts = 3
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            with httpx.Client(timeout=timeout, headers=DEFAULT_HEADERS, follow_redirects=True) as client:
                response = client.get(url)

            response.raise_for_status()
            return response.text
        except httpx.TimeoutException as exc:
            last_error = exc
            LOGGER.warning("Timeout fetching iCal (attempt %s/%s): %s", attempt, max_attempts, url)
        except httpx.HTTPStatusError as exc:
            last_error = exc
            status = exc.response.status_code
            LOGGER.warning(
                "HTTP %s fetching iCal (attempt %s/%s): %s",
                status,
                attempt,
                max_attempts,
                url,
            )
        except httpx.HTTPError as exc:
            last_error = exc
            LOGGER.warning(
                "Network error fetching iCal (attempt %s/%s): %s (%s)",
                attempt,
                max_attempts,
                url,
                exc,
            )

        if attempt < max_attempts:
            backoff = 2 ** (attempt - 1)
            time.sleep(backoff)

    raise RuntimeError(f"Failed to fetch iCal after {max_attempts} attempts: {url}") from last_error


def fetch_all_icals(
    properties: list[PropertyConfig],
    timeout: int,
    delay: float,
) -> dict[str, str | None]:
    """Download iCal feeds for all properties with rate limiting.

    Args:
        properties: Property list from config.
        timeout: Request timeout in seconds.
        delay: Delay between requests in seconds.

    Returns:
        Mapping {property_id: iCal content or None on failure}.
    """
    result: dict[str, str | None] = {}

    for index, property_config in enumerate(properties):
        try:
            LOGGER.info("Fetching iCal for property=%s (%s)", property_config.id, property_config.name)
            result[property_config.id] = fetch_ical(str(property_config.ical_url), timeout=timeout)
            LOGGER.info("Fetched iCal successfully for property=%s", property_config.id)
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.warning("Failed to fetch property=%s: %s", property_config.id, exc)
            result[property_config.id] = None

        is_last = index == len(properties) - 1
        if not is_last and delay > 0:
            time.sleep(delay)

    return result

