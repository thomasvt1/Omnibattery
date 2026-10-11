"""Directional battery conversion assumptions and optional measured evidence.

Driver defaults are explicit compatibility assumptions, not measured claims.
Measurements must pair input/output energy across the same isolated converter.
"""
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import math


@dataclass(frozen=True)
class BatteryEnergyModel:
    charge_efficiency: float = 0.85
    discharge_efficiency: float = 0.85
    charge_crossover_w: float = 1750.0
    discharge_crossover_w: float = 1500.0
    source: str = "legacy_assumption"

    def __post_init__(self):
        for name in ("charge_efficiency", "discharge_efficiency"):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0 < value <= 1:
                raise ValueError(f"invalid {name}")
        for name in ("charge_crossover_w", "discharge_crossover_w"):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f"invalid {name}")

    @property
    def round_trip_efficiency(self):
        return self.charge_efficiency * self.discharge_efficiency


@dataclass(frozen=True)
class EfficiencyMeasurement:
    input_kwh: float
    output_kwh: float
    duration_s: float
    samples: int
    observed_at: datetime
    isolated_converter: bool = False

    def efficiency(self, now):
        """Reject short, stale, non-finite or PV-contaminated observations."""
        try:
            age = (now - self.observed_at).total_seconds()
            ratio = self.output_kwh / self.input_kwh
            if (self.isolated_converter and self.samples >= 30 and self.duration_s >= 300
                    and all(math.isfinite(v) for v in (self.input_kwh, self.output_kwh, self.duration_s, ratio))
                    and self.input_kwh >= 0.05 and 0.5 <= ratio <= 1 and 0 <= age <= 86400):
                return ratio
        except (TypeError, ValueError, ZeroDivisionError, OverflowError):
            pass
        return None


def battery_energy_model(coordinator, now=None):
    """Use validated driver evidence when supplied; otherwise keep its defaults."""
    model = getattr(getattr(coordinator, "capabilities", None), "energy_model", None)
    if not isinstance(model, BatteryEnergyModel):
        model = BatteryEnergyModel()
    evidence = getattr(getattr(coordinator, "driver", None), "efficiency_measurements", {})
    if not isinstance(evidence, dict):
        return model
    changes = {}
    for direction in ("charge", "discharge"):
        reading = evidence.get(direction)
        if isinstance(reading, EfficiencyMeasurement):
            value = reading.efficiency(now or datetime.now(timezone.utc))
            if value is not None:
                changes[f"{direction}_efficiency"] = value
    return replace(model, **changes, source="measured:" + ",".join(changes)) if changes else model


def fleet_charge_efficiency(coordinators):
    """Conservative bound while dispatch may choose any eligible battery."""
    return min((battery_energy_model(c).charge_efficiency for c in coordinators), default=0.85)
