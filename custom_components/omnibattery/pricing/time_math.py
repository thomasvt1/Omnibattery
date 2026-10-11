"""Absolute-time arithmetic at legacy local-wall-clock boundaries.

Provider intervals retain aware UTC timestamps. Older configuration and controller
callers may pass naive local times; interpret those in Home Assistant's timezone,
including their fold flag, before comparing or measuring elapsed time.
"""
from datetime import datetime, timezone
from homeassistant.util import dt as dt_util


def instant(value):
    """Normalize datetime operands without changing numeric/date operands."""
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
    return value.astimezone(timezone.utc)


def elapsed(left, right):
    """Subtract elapsed instants, preserving ordinary numeric subtraction."""
    if isinstance(left, datetime) and isinstance(right, datetime):
        return instant(left) - instant(right)
    return left - right


def local_time(value: datetime) -> datetime:
    """Render a provider instant in the installation's timezone."""
    return dt_util.as_local(instant(value))


def time_min(*values, **kwargs):
    """Select the earliest boundary while retaining its original representation."""
    return min(*values, key=instant, **kwargs)


def time_max(*values, **kwargs):
    """Select the latest boundary while retaining its original representation."""
    return max(*values, key=instant, **kwargs)
