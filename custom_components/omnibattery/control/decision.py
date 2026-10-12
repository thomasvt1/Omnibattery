"""Immutable, pure contracts at the final battery command boundary.

A decision records validated intent. Driver acknowledgement and physical power
remain separate observations owned by the existing execution path.
"""
from dataclasses import dataclass, replace
import math


def _number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) and not isinstance(value, bool) else None
    except (TypeError, ValueError, OverflowError):
        return None


@dataclass(frozen=True)
class ControlInputs:
    requested_charge_w: float
    requested_discharge_w: float
    requested_owner: str = 'automatic'
    available: bool = True
    manual_owned: bool = False
    backup_owned: bool = False
    external_owned: bool = False
    slot_owned: bool = False
    charge_cap_w: float | None = None
    discharge_cap_w: float | None = None
    charge_blockers: tuple[str, ...] = ()
    discharge_blockers: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, 'charge_blockers', tuple(self.charge_blockers))
        object.__setattr__(self, 'discharge_blockers', tuple(self.discharge_blockers))


@dataclass(frozen=True)
class ControlDecision:
    requested_owner: str
    requested_charge_w: float | None
    requested_discharge_w: float | None
    charge_cap_w: float | None
    discharge_cap_w: float | None
    allowed: bool
    charge_power_w: int = 0
    discharge_power_w: int = 0
    reasons: tuple[str, ...] = ()

    @property
    def net_power_w(self):
        return self.charge_power_w - self.discharge_power_w


def decide_control(inputs: ControlInputs) -> ControlDecision:
    charge, discharge = _number(inputs.requested_charge_w), _number(inputs.requested_discharge_w)
    caps = tuple(None if value is None else max(0.0, _number(value) or 0.0)
                 for value in (inputs.charge_cap_w, inputs.discharge_cap_w))
    reasons = []
    if inputs.requested_owner not in ("automatic", "battery_manual"):
        reasons.append("invalid_owner")
    if inputs.requested_owner == 'automatic' and inputs.manual_owned:
        reasons.append('manual_owner')
    if not inputs.available:
        reasons.append('unavailable')
    if inputs.backup_owned:
        reasons.append('backup_owner')
    if inputs.external_owned:
        reasons.append('external_owner')
    if inputs.requested_owner == 'automatic' and inputs.slot_owned:
        reasons.append('manual_slot_owner')
    if charge is None or discharge is None or min(charge, discharge) < 0 or (charge > 0 and discharge > 0):
        reasons.append('invalid_power_request')
    decision = ControlDecision(inputs.requested_owner, charge, discharge, *caps,
                               allowed=not reasons, reasons=tuple(reasons))
    if reasons:
        return decision
    powers = [charge, discharge]
    for i, direction in enumerate(('charge', 'discharge')):
        if caps[i] is not None and powers[i] > caps[i]:
            powers[i] = caps[i]
            reasons.append(direction + '_cap')
        blockers = getattr(inputs, direction + '_blockers')
        if blockers and powers[i] > 0:
            powers[i] = 0
            reasons.extend(direction + ':' + str(key) for key in sorted(set(blockers)))
    return replace(decision, charge_power_w=math.floor(powers[0]),
                   discharge_power_w=math.floor(powers[1]), reasons=tuple(reasons))


def apply_phase_limits(decision: ControlDecision, charge, discharge) -> ControlDecision:
    """A downstream limiter may only reduce an already validated direction."""
    if not decision.allowed:
        return decision
    values = [_number(charge), _number(discharge)]
    powers = [decision.charge_power_w, decision.discharge_power_w]
    reduced = [math.floor(min(p, max(0.0, v or 0.0))) for p,v in zip(powers,values)]
    reason = 'invalid_phase_limit' if None in values else 'phase_limit'
    reasons = decision.reasons + ((reason,) if reduced != powers or None in values else ())
    return replace(decision, charge_power_w=reduced[0], discharge_power_w=reduced[1], reasons=reasons)
