"""
Desktop notification utilities for Driftbase.

Provides cross-platform desktop notifications for drift alerts.
"""

from __future__ import annotations

import logging
import platform
import subprocess
from typing import Literal

logger = logging.getLogger(__name__)

NotificationLevel = Literal["info", "warning", "critical"]


def is_notification_supported() -> bool:
    """Check if desktop notifications are supported on this platform."""
    system = platform.system()

    if system == "Darwin":  # macOS
        return True
    elif system == "Linux":
        # Check if notify-send is available
        try:
            result = subprocess.run(
                ["which", "notify-send"],
                capture_output=True,
                timeout=1,
                check=False,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    elif system == "Windows":
        # Check if win10toast can be imported
        try:
            import win10toast  # noqa: F401

            return True
        except ImportError:
            return False
    else:
        return False


def send_notification(
    title: str,
    message: str,
    level: NotificationLevel = "info",
    sound: bool = True,
) -> bool:
    """
    Send a desktop notification.

    Args:
        title: Notification title
        message: Notification message body
        level: Notification level (info, warning, critical)
        sound: Whether to play notification sound

    Returns:
        True if notification was sent successfully, False otherwise
    """
    system = platform.system()

    try:
        if system == "Darwin":  # macOS
            return _send_macos_notification(title, message, level, sound)
        elif system == "Linux":
            return _send_linux_notification(title, message, level)
        elif system == "Windows":
            return _send_windows_notification(title, message, level)
        else:
            logger.debug(f"Notifications not supported on {system}")
            return False
    except Exception as e:
        logger.debug(f"Failed to send notification: {e}")
        return False


def _send_macos_notification(
    title: str, message: str, level: NotificationLevel, sound: bool
) -> bool:
    """Send notification on macOS using osascript."""
    # Map level to system icon
    icon_map = {
        "info": "note",
        "warning": "caution",
        "critical": "stop",
    }
    icon = icon_map.get(level, "note")

    # Build AppleScript
    sound_clause = 'sound name "default"' if sound else ""

    script = f'''
        display notification "{message}" ¬
            with title "Driftbase" ¬
            subtitle "{title}" ¬
            {sound_clause}
    '''

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            timeout=5,
            check=False,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.debug(f"Failed to send macOS notification: {e}")
        return False


def _send_linux_notification(
    title: str, message: str, level: NotificationLevel
) -> bool:
    """Send notification on Linux using notify-send."""
    # Map level to urgency
    urgency_map = {
        "info": "normal",
        "warning": "normal",
        "critical": "critical",
    }
    urgency = urgency_map.get(level, "normal")

    try:
        result = subprocess.run(
            [
                "notify-send",
                "--app-name=Driftbase",
                f"--urgency={urgency}",
                title,
                message,
            ],
            capture_output=True,
            timeout=5,
            check=False,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.debug(f"Failed to send Linux notification: {e}")
        return False


def _send_windows_notification(
    title: str, message: str, level: NotificationLevel
) -> bool:
    """Send notification on Windows using win10toast."""
    try:
        from win10toast import ToastNotifier

        toaster = ToastNotifier()

        # Map level to duration
        duration_map = {
            "info": 5,
            "warning": 10,
            "critical": 15,
        }
        duration = duration_map.get(level, 5)

        toaster.show_toast(
            f"Driftbase - {title}",
            message,
            duration=duration,
            threaded=True,
        )
        return True
    except ImportError:
        logger.debug("win10toast not available")
        return False
    except Exception as e:
        logger.debug(f"Failed to send Windows notification: {e}")
        return False


def send_drift_alert(
    baseline_version: str,
    current_version: str,
    drift_score: float,
    threshold: float,
) -> bool:
    """
    Send a drift alert notification.

    Args:
        baseline_version: Baseline version name
        current_version: Current version name
        drift_score: Detected drift score
        threshold: Configured threshold

    Returns:
        True if notification was sent successfully
    """
    # Determine severity
    if drift_score >= threshold * 2:
        level: NotificationLevel = "critical"
        emoji = "🚨"
    elif drift_score >= threshold:
        level = "warning"
        emoji = "⚠️"
    else:
        level = "info"
        emoji = "ℹ️"

    title = f"{emoji} Drift Detected"
    message = (
        f"{current_version} vs {baseline_version}\n"
        f"Drift: {drift_score:.3f} (threshold: {threshold:.3f})"
    )

    return send_notification(title, message, level=level)


def send_error_alert(error_message: str) -> bool:
    """
    Send an error alert notification.

    Args:
        error_message: Error message to display

    Returns:
        True if notification was sent successfully
    """
    return send_notification(
        title="Error",
        message=error_message,
        level="critical",
        sound=True,
    )
