"""Native forecast curves with explicit units and unambiguous timestamps."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
import re
from typing import Any
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class ProviderCurve:
    periods: tuple[tuple[datetime, datetime, float], ...] = ()
    source: str = 'scalar_fallback'
    reason: str | None = None


def _timestamp(value: Any, zone_name: str | None) -> datetime:
    stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if stamp.tzinfo is not None:
        return stamp.astimezone(timezone.utc)
    if not zone_name:
        raise ValueError('naive timestamp without provider timezone')
    zone = ZoneInfo(zone_name)
    candidates = set()
    for fold in (0, 1):
        candidate = stamp.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
        if candidate.astimezone(zone).replace(tzinfo=None) == stamp:
            candidates.add(candidate)
    if len(candidates) != 1:
        raise ValueError('ambiguous or nonexistent provider local time')
    return candidates.pop()


def _number(value: Any) -> float:
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError('invalid forecast value')
    return value


def _duration(value: Any = 'PT30M') -> timedelta:
    match = re.fullmatch(r'PT(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?', str(value))
    if not match:
        raise ValueError('invalid ISO duration')
    hours, minutes, seconds = (float(v or 0) for v in match.groups())
    result = timedelta(hours=hours, minutes=minutes, seconds=seconds)
    if not 0 < result.total_seconds() <= 7200:
        raise ValueError('unsupported period duration')
    return result


def _validated(rows, source):
    previous_end = None
    for start, end, energy in rows:
        if end <= start or not math.isfinite(energy) or energy < 0:
            raise ValueError('invalid period')
        if previous_end is not None and start != previous_end:
            raise ValueError('duplicate, unordered, overlapping or missing period')
        previous_end = end
    if not rows:
        raise ValueError('empty curve')
    return ProviderCurve(tuple(rows), source)


def adapt_native_forecast(attributes: dict) -> ProviderCurve | None:
    """Return None for non-native attributes; invalid native data stays explicit."""
    result = attributes.get("result", attributes)
    if "detailedForecast" not in attributes and not (isinstance(result, dict) and any(k in result for k in ("watt_hours_period", "watts"))):
        return None
    source = None
    try:
        info = (attributes.get('message') or {}).get('info') or {}
        zone = attributes.get('timezone') or info.get('timezone')
        if 'detailedForecast' in attributes:
            source = 'solcast'
            rows = []
            for raw in attributes['detailedForecast']:
                duration = _duration(raw.get('period', 'PT30M'))
                if 'period_start' in raw:
                    start = _timestamp(raw['period_start'], zone)
                    end = _timestamp(raw['period_end'], zone) if 'period_end' in raw else start + duration
                else:
                    end = _timestamp(raw['period_end'], zone)
                    start = end - duration
                hours = (end - start).total_seconds() / 3600
                if not 0 < hours <= 2:
                    raise ValueError('invalid Solcast interval')
                rows.append((start, end, _number(raw['pv_estimate']) * hours))
            return _validated(rows, source)
        result = attributes.get('result', attributes)
        if not isinstance(result, dict):
            return None
        kind = 'watt_hours_period' if 'watt_hours_period' in result else 'watts' if 'watts' in result else None
        if kind is None:
            return None
        source = 'forecast_solar_' + kind
        points = sorted((_timestamp(k, zone), _number(v)) for k,v in result[kind].items())
        if len({p[0] for p in points}) != len(points):
            raise ValueError('duplicate instant')
        rows = []
        previous = None
        for stamp, value in points:
            if previous is None:
                if kind == 'watt_hours_period' and value > 0:
                    minutes = attributes.get('period_minutes')
                    if minutes is None:
                        raise ValueError('first interval energy has no start boundary')
                    previous = (stamp - _duration(f'PT{minutes}M'), 0.0)
                else:
                    previous = (stamp, value)
                    continue
            start, old_value = previous
            seconds = (stamp - start).total_seconds()
            # Native multi-day curves carry explicit zero-energy night gaps.
            # Positive-energy gaps still need normal period spacing.
            zero_gap = value == 0 and old_value == 0
            if not 0 < seconds <= (86400 if zero_gap else 7200):
                raise ValueError('invalid or missing Forecast.Solar interval')
            energy = value / 1000 if kind == 'watt_hours_period' else (old_value + value) / 2 * seconds / 3_600_000
            rows.append((start, stamp, energy))
            previous = (stamp, value)
        return _validated(rows, source)
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return ProviderCurve(reason='invalid_' + (source or 'native') + '_periods')
