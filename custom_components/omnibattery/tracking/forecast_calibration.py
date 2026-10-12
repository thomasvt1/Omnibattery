"""Bounded, causal forecast scoring against complete production horizons.

Snapshots are immutable within a source/local-day/6-hour issuance bucket.
Only fully observed, uncensored horizons train the conservative error reserve.
"""
from __future__ import annotations

import math
from datetime import datetime, time, timedelta
from typing import Any


class ForecastCalibration:
    """Small serializable journal; callers provide aware wall-clock instants."""

    def __init__(self) -> None:
        self.pending: list[dict[str, Any]] = []
        self.outcomes: list[dict[str, Any]] = []
        self._last: tuple[float, float | None, bool] | None = None

    def issue(self, source: str, now: datetime, forecast_kwh: float) -> bool:
        end = datetime.combine(now.date() + timedelta(days=1), time.min, now.tzinfo)
        start, finish = now.timestamp(), end.timestamp()
        if (now.tzinfo is None or not math.isfinite(forecast_kwh)
                or forecast_kwh <= 0 or finish - start < 4 * 3600):
            return False
        bucket = now.hour // 6
        key = (source, now.date().isoformat(), bucket)
        if any((r['source'], r['day'], r['bucket']) == key
               for r in self.pending + self.outcomes):
            return False
        self.pending.append(dict(source=source, day=key[1], bucket=bucket,
                                 start=start, end=finish, forecast_kwh=forecast_kwh,
                                 actual_kwh=0.0, covered_s=0.0, censored=False))
        self.pending = self.pending[-16:]
        return True

    def observe(self, now: datetime, power_kw: float | None, *, censored: bool = False) -> None:
        stamp = now.timestamp()
        if now.tzinfo is None or not math.isfinite(stamp):
            return
        if power_kw is not None and (not math.isfinite(power_kw) or power_kw < 0):
            power_kw = None
        previous = self._last
        # A clock reversal must never integrate overlapping time twice.
        if previous and stamp <= previous[0]:
            return
        for row in self.pending:
            if previous:
                old, old_power, old_censored = previous
                left, right = max(old, row['start']), min(stamp, row['end'])
                if right > left:
                    row['censored'] |= censored or old_censored
                    if (0 < stamp - old <= 120 and old_power is not None
                            and power_kw is not None):
                        # Interpolate the clipped endpoints, not the full sample's mean.
                        slope = (power_kw - old_power) / (stamp - old)
                        mean = old_power + slope * ((left + right) / 2 - old)
                        row['actual_kwh'] += mean * (right - left) / 3600
                        row['covered_s'] += right - left
            if stamp >= row['end']:
                duration = row['end'] - row['start']
                row['scored'] = not row['censored'] and row['covered_s'] >= duration - 0.001
                # Missing coverage stays unscored, including an all-missing horizon.
                self.outcomes.append(dict(row))
        self.pending = [r for r in self.pending if r['end'] > stamp]
        self.outcomes = [r for r in self.outcomes if r['end'] >= stamp - 90 * 86400][-240:]
        self._last = (stamp, power_kw, censored)

    def stats(self, source: str, now: datetime) -> dict[str, Any]:
        rows = [r for r in self.outcomes if r.get('scored') and r['source'] == source
                and r['bucket'] == now.hour // 6
                and now.timestamp() - 90 * 86400 <= r['end'] <= now.timestamp()]
        # One observation per local day/bucket, even after a corrupt/duplicated import.
        rows = list({r['day']: r for r in rows}.values())
        errors = [r['forecast_kwh'] - r['actual_kwh'] for r in rows]
        fractions = sorted(max(0.0, e / r['forecast_kwh']) for e, r in zip(errors, rows))
        calibrated = len(rows) >= 10
        reserve = min(.30, fractions[math.ceil(.9 * len(rows)) - 1]) if calibrated else 0.0
        return dict(samples=len(rows), calibrated=calibrated, reserve_fraction=reserve,
                    bias_kwh=sum(errors) / len(errors) if errors else None,
                    mean_absolute_error_kwh=sum(map(abs, errors)) / len(errors) if errors else None,
                    policy='p90_optimistic_error_capped_30_percent')

    def dump(self) -> dict[str, Any]:
        return dict(version=1, pending=[dict(r) for r in self.pending],
                    outcomes=[dict(r) for r in self.outcomes])

    def restore(self, data: Any) -> None:
        """Validate stored evidence; never interpolate across a process restart."""
        self.pending, self.outcomes, self._last = [], [], None
        if not isinstance(data, dict) or data.get('version') != 1:
            return
        seen = set()
        for field, limit in (('outcomes', 240), ('pending', 16)):
            values = data.get(field, [])
            if not isinstance(values, list):
                continue
            for raw in values[-limit:]:
                try:
                    row = dict(raw)
                    key = (row['source'], row['day'], row['bucket'])
                    datetime.fromisoformat(row['day'])
                    numbers = [float(row[k]) for k in ('start', 'end', 'forecast_kwh', 'actual_kwh', 'covered_s')]
                    start, end, forecast, actual, covered = numbers
                    if (not isinstance(row['source'], str) or len(row['source']) > 512
                            or row['bucket'] not in range(4) or key in seen
                            or not all(math.isfinite(v) for v in numbers)
                            or not 4 * 3600 <= end - start <= 25 * 3600
                            or forecast <= 0 or actual < 0 or not 0 <= covered <= end - start + .001
                            or not isinstance(row['censored'], bool)):
                        continue
                    row.update(zip(('start', 'end', 'forecast_kwh', 'actual_kwh', 'covered_s'), numbers))
                    if field == 'outcomes':
                        row['scored'] = (raw.get('scored') is True and not row['censored']
                                         and covered >= end - start - .001)
                    getattr(self, field).append(row)
                    seen.add(key)
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
