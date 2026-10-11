"""Temperature-based charge power derate (TemperatureChargeLimitManager).

Optional, charge-only thermal protection. When a battery's internal temperature
rises above a configured limit, the per-battery charge power is proportionally
reduced: full power at/below the limit, ramping linearly down to a floor (a
percentage of the normal charge ceiling) as the temperature climbs across the
band, and back up as it cools. The ramp is continuous, so no cooldown latch or
hysteresis is needed (it self-stabilises).

This mirrors ``MaxSocChargeManager.apply_charge_taper``'s cap-and-return
contract: it is called from ``_battery_power_limit`` with the current per-battery
limit and returns a limit that is never higher than the one passed in. When the
feature is disabled or the temperature is unavailable it returns the limit
unchanged after a bounded hold of the last valid derated cap. A missing sensor
is reported explicitly; this optional derate is not a substitute for the BMS.
"""
from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)
THERMAL_HOLD_SECONDS = 300.0


class TemperatureChargeLimitManager:
    """Proportional per-battery charge-power derate driven by internal temperature."""

    def __init__(self, hass: "HomeAssistant", controller: Any) -> None:
        self._hass = hass
        self._controller = controller
        self._last_limits: dict[tuple[int, bool], tuple[float, int]] = {}

    def _derate_factor(self, temp: float) -> float:
        """Return the charge-power scale (0..1) for a given temperature.

        1.0 at/below the limit; ramps linearly to the floor across the band;
        pinned at the floor at/above ``limit + band``.
        """
        c = self._controller
        limit_c = c._temp_charge_limit_c
        band_c = c._temp_charge_limit_band_c
        floor = c._temp_charge_limit_floor_pct / 100.0

        if temp <= limit_c:
            return 1.0
        if band_c <= 0 or temp >= limit_c + band_c:
            return floor
        frac = (temp - limit_c) / band_c  # 0..1 across the band
        return 1.0 - frac * (1.0 - floor)

    @staticmethod
    def _min_power(coordinator, is_charging: bool) -> int:
        """The battery's minimum reliable operating power (0 when it has none).

        Read from the driver capabilities (0 for drivers with no such floor).
        """
        caps = getattr(coordinator, "capabilities", None)
        attr = "min_charge_power_w" if is_charging else "min_discharge_power_w"
        return int(getattr(caps, attr, 0) or 0)

    @staticmethod
    def _temperature(coordinator):
        """Return the reading and its real age; cached poll values are not new data."""
        try:
            value = float((coordinator.data or {}).get("internal_temperature"))
        except (TypeError, ValueError):
            return None, 0.0
        if not math.isfinite(value):
            return None, 0.0
        times = getattr(coordinator, "_key_update_times", None)
        if times is None:  # Lightweight consumers without per-key freshness.
            return value, 0.0
        stamp = times.get("internal_temperature")
        if not isinstance(stamp, datetime) or stamp.tzinfo is None:
            return None, 0.0
        age = max(0.0, (datetime.now(timezone.utc) - stamp).total_seconds())
        return (value if age <= 60.0 else None), age

    def _apply(self, coordinator, limit: int, is_charging: bool) -> int:
        """Cap ``limit`` by the thermal derate factor (fail-safe passthrough)."""
        temp_f, age = self._temperature(coordinator)
        key = (id(coordinator), is_charging)
        now = time.monotonic()
        if temp_f is None:
            previous = self._last_limits.get(key)
            if previous is not None and now - previous[0] <= THERMAL_HOLD_SECONDS:
                return min(limit, previous[1])
            self._last_limits.pop(key, None)
            return limit

        factor = self._derate_factor(temp_f)
        if factor >= 1.0:
            self._last_limits.pop(key, None)
            return limit
        derated = min(limit, int(round(limit * factor)))
        # Hard floor: never command a non-zero power below the battery's minimum
        # reliable operating power (0 when the driver declares none). Never raise
        # above a limit that was already below that floor.
        result = max(derated, min(self._min_power(coordinator, is_charging), limit))
        self._last_limits[key] = (now - age, result)
        return result

    def apply_temperature_limit(self, coordinator, limit: int) -> int:
        """Cap the per-battery charge limit by the thermal derate factor."""
        if not self._controller.temp_charge_limit_enabled:
            return limit
        return self._apply(coordinator, limit, True)

    def apply_discharge_limit(self, coordinator, limit: int) -> int:
        """Cap the per-battery discharge limit, when opted in.

        Uses the same (charge-tuned) curve; discharge tolerates heat better, so
        this is a compromise whose main value is avoiding the BMS hard cutoff.
        """
        c = self._controller
        if not (c.temp_charge_limit_enabled and c.temp_limit_apply_discharge):
            return limit
        return self._apply(coordinator, limit, False)

    def get_status(self) -> dict:
        """Return per-battery thermal-derate diagnostics for the status sensor."""
        c = self._controller
        status: dict = {}
        for coordinator in c.coordinators:
            temp_f, _ = self._temperature(coordinator)
            previous = self._last_limits.get((id(coordinator), True))
            held = previous is not None and time.monotonic() - previous[0] <= THERMAL_HOLD_SECONDS
            factor = self._derate_factor(temp_f) if temp_f is not None else None
            status[coordinator.name] = {
                "enabled": c.temp_charge_limit_enabled,
                "apply_discharge": c.temp_limit_apply_discharge,
                "internal_temperature": temp_f,
                "telemetry_status": "valid" if temp_f is not None else ("held" if held else "unavailable"),
                "held_charge_limit_w": previous[1] if held and temp_f is None else None,
                "hold_seconds": THERMAL_HOLD_SECONDS,
                "limit_c": c._temp_charge_limit_c,
                "band_c": c._temp_charge_limit_band_c,
                "floor_pct": c._temp_charge_limit_floor_pct,
                "derate_factor": round(factor, 3) if factor is not None else None,
                "derating": c.temp_charge_limit_enabled and temp_f is not None and factor < 1.0,
            }
        return status
