"""Unit tests for TemperatureChargeLimitManager (thermal charge derate).

No hardware, no Home Assistant: the manager only stores ``hass``/``controller``
references and reads plain attributes off the controller stub, so it is built
directly. ``apply_temperature_limit`` mirrors ``apply_charge_taper``'s
cap-and-return contract, so the assertions are on the returned integer limit.

The derate enforces a hard floor equal to the battery's minimum operating power,
read from ``coordinator.capabilities`` (v2/v3 = 800 W, vA/vD/Zendure = 0). Most
cases use a realistic 2500 W ceiling with an 800 W floor so the ramp stays above it.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.omnibattery.control.temperature_limit import (
    TemperatureChargeLimitManager,
)

CEIL = 2500  # realistic per-battery charge ceiling
FLOOR_W = 800  # v3/vA minimum operating power


class _Coord:
    """Coordinator stand-in with a ``data`` dict and driver ``capabilities``.

    ``min_power`` models the hardware floor: 800 for v2/v3, 0 for vA/vD/Zendure.
    """

    def __init__(self, name="bat", *, data=None, min_power=FLOOR_W):
        self.name = name
        self.data = {} if data is None else data
        self.capabilities = SimpleNamespace(
            min_charge_power_w=min_power,
            min_discharge_power_w=min_power,
        )


def _mgr(
    *,
    enabled=True,
    limit_c=40,
    band_c=10,
    floor_pct=40,
    apply_discharge=False,
    coords=None,
):
    ctrl = SimpleNamespace(
        temp_charge_limit_enabled=enabled,
        temp_limit_apply_discharge=apply_discharge,
        _temp_charge_limit_c=limit_c,
        _temp_charge_limit_band_c=band_c,
        _temp_charge_limit_floor_pct=floor_pct,
        coordinators=coords or [],
    )
    return TemperatureChargeLimitManager(hass=None, controller=ctrl)


def _cap(temp, limit=CEIL, *, min_power=FLOOR_W, **kw):
    mgr = _mgr(**kw)
    coord = _Coord(data={"internal_temperature": temp}, min_power=min_power)
    return mgr.apply_temperature_limit(coord, limit)


# ----------------------------------------------------------------------
# Derate curve (2500 W ceiling: ramp stays above the 800 W floor)
# ----------------------------------------------------------------------

def test_below_limit_full_power():
    assert _cap(35) == 2500
    assert _cap(40) == 2500  # exactly at the limit is still full power


def test_midband_is_linear():
    # limit 40, band 10, floor 40%: at 45 C -> halfway -> factor 0.7 -> 1750 W
    assert _cap(45) == 1750


def test_at_and_above_band_pins_to_floor():
    assert _cap(50) == 1000  # limit + band -> 40% of 2500
    assert _cap(60) == 1000  # beyond the band stays at the floor


def test_zero_band_steps_to_floor_above_limit():
    assert _cap(40, band_c=0) == 2500  # at the limit: unchanged
    assert _cap(41, band_c=0) == 1000  # any excess -> 40% floor


def test_never_exceeds_incoming_limit():
    # A cool battery returns the limit untouched (min-cap contract).
    assert _cap(30, limit=500) == 500


@pytest.mark.parametrize("temp,expected", [(40, 2500), (42.5, 2125), (47.5, 1375), (50, 1000)])
def test_curve_points(temp, expected):
    assert _cap(temp) == expected


# ----------------------------------------------------------------------
# Hard floor from the battery's minimum operating power (capabilities)
# ----------------------------------------------------------------------

def test_clamps_up_to_floor_when_derate_would_go_lower():
    # 20% of 2500 = 500 W, below the 800 W minimum -> clamped up to 800.
    assert _cap(50, floor_pct=20) == FLOOR_W


def test_floor_zero_clamps_to_hw_floor_when_present():
    # floor 0 would ask for 0 W over the band; the 800 W hw floor makes it 800 W.
    assert _cap(55, floor_pct=0) == FLOOR_W
    # ...but mid-band it is still above the floor and rides the ramp.
    assert _cap(45, floor_pct=0) == 1250  # 2500 * 0.5


def test_vd_has_no_floor_so_floor_zero_stops():
    # vD/Zendure report min_power 0: the derate can reach a full stop.
    assert _cap(55, floor_pct=0, min_power=0) == 0
    assert _cap(50, floor_pct=20, min_power=0) == 500  # no clamp-up


def test_never_raises_a_limit_already_below_floor():
    # A 500 W ceiling stays 500 W even when hot; the clamp must not raise it.
    assert _cap(55, limit=500) == 500
    assert _cap(50, limit=700, floor_pct=0) == 700


# ----------------------------------------------------------------------
# Fail-safe / gating
# ----------------------------------------------------------------------

def test_disabled_passes_through():
    assert _cap(55, enabled=False) == 2500


def test_missing_temperature_passes_through():
    mgr = _mgr()
    assert mgr.apply_temperature_limit(_Coord(data={}), CEIL) == 2500
    assert mgr.apply_temperature_limit(_Coord(data=None), CEIL) == 2500


def test_non_numeric_temperature_passes_through():
    assert _cap("n/a") == 2500


# ----------------------------------------------------------------------
# Discharge sub-toggle
# ----------------------------------------------------------------------

def _dcap(temp, limit=CEIL, *, min_power=FLOOR_W, **kw):
    mgr = _mgr(**kw)
    coord = _Coord(data={"internal_temperature": temp}, min_power=min_power)
    return mgr.apply_discharge_limit(coord, limit)


def test_discharge_off_by_default():
    # Feature enabled but discharge sub-toggle off: discharge untouched.
    assert _dcap(45) == 2500


def test_discharge_on_applies_same_curve_and_floor():
    assert _dcap(45, apply_discharge=True) == 1750
    assert _dcap(50, apply_discharge=True, floor_pct=20) == FLOOR_W


def test_discharge_requires_feature_enabled():
    # Sub-toggle on but whole feature off: still a passthrough.
    assert _dcap(45, enabled=False, apply_discharge=True) == 2500


# ----------------------------------------------------------------------
# Status
# ----------------------------------------------------------------------

def test_get_status_reports_per_battery():
    c1 = _Coord("hot", data={"internal_temperature": 45})
    c2 = _Coord("cool", data={"internal_temperature": 30})
    status = _mgr(coords=[c1, c2]).get_status()
    assert status["hot"]["derating"] is True
    assert status["hot"]["derate_factor"] == 0.7
    assert status["cool"]["derating"] is False
    assert status["cool"]["derate_factor"] == 1.0


# ----------------------------------------------------------------------
# Integration: the real ChargeDischargeController._battery_power_limit hook
#
# Drives the actual production method (not the manager in isolation) with a
# duck-typed ``self``, so the wiring is exercised: charge goes taper -> temp
# derate -> slot ceiling; discharge goes temp derate -> slot ceiling. The
# real TemperatureChargeLimitManager reads its mirrors off this same ``self``.
# ----------------------------------------------------------------------

from custom_components.omnibattery import ChargeDischargeController  # noqa: E402


def _ctrl_self(*, enabled=True, apply_discharge=False, limit_c=40, band_c=10, floor_pct=40):
    ns = SimpleNamespace(
        temp_charge_limit_enabled=enabled,
        temp_limit_apply_discharge=apply_discharge,
        _temp_charge_limit_c=limit_c,
        _temp_charge_limit_band_c=band_c,
        _temp_charge_limit_floor_pct=floor_pct,
        # max-SOC taper is a no-op here (identity), so the temp derate is isolated.
        _max_soc_mgr=SimpleNamespace(apply_charge_taper=lambda coord, limit: limit),
        # slot ceiling: identity (no active slot override in the test).
        _apply_slot_power_ceiling=lambda coord, is_charging, limit: limit,
    )
    ns._temp_limit_mgr = TemperatureChargeLimitManager(hass=None, controller=ns)
    return ns


def _limit(self_ns, coord, is_charging):
    return ChargeDischargeController._battery_power_limit(self_ns, coord, is_charging)


def test_hook_charge_derates_when_hot():
    coord = _Coord(data={"internal_temperature": 45})
    coord.max_charge_power = 2500
    assert _limit(_ctrl_self(), coord, True) == 1750  # 2500 * 0.7


def test_hook_charge_untouched_when_cool():
    coord = _Coord(data={"internal_temperature": 30})
    coord.max_charge_power = 2500
    assert _limit(_ctrl_self(), coord, True) == 2500


def test_hook_charge_no_data_passes_ceiling():
    coord = _Coord(data=None)
    coord.max_charge_power = 2500
    assert _limit(_ctrl_self(), coord, True) == 2500


def test_hook_discharge_off_by_default():
    coord = _Coord(data={"internal_temperature": 45})
    coord.max_discharge_power = 2500
    assert _limit(_ctrl_self(), coord, False) == 2500


def test_hook_discharge_derates_when_opted_in():
    coord = _Coord(data={"internal_temperature": 45})
    coord.max_discharge_power = 2500
    assert _limit(_ctrl_self(apply_discharge=True), coord, False) == 1750

@pytest.mark.parametrize('invalid', [float('nan'), float('inf'), -float('inf'), None, 'bad'])
def test_invalid_temperature_holds_hot_cap_then_expires(monkeypatch, invalid):
    from custom_components.omnibattery.control import temperature_limit as module
    clock=[0.0]
    monkeypatch.setattr(module.time,'monotonic',lambda:clock[0])
    coord=_Coord(data={'internal_temperature':55})
    mgr=_mgr(coords=[coord])
    assert mgr.apply_temperature_limit(coord,2500)==1000
    coord.data['internal_temperature']=invalid
    clock[0]=10
    assert mgr.apply_temperature_limit(coord,2500)==1000
    assert mgr.apply_temperature_limit(coord,500)==500
    assert mgr.get_status()['bat']['telemetry_status']=='held'
    clock[0]=301
    assert mgr.apply_temperature_limit(coord,2500)==2500
    assert mgr.get_status()['bat']['telemetry_status']=='unavailable'
    coord.data['internal_temperature']=35
    assert mgr.apply_temperature_limit(coord,2500)==2500
    assert mgr.get_status()['bat']['telemetry_status']=='valid'


def test_cached_temperature_does_not_refresh_hold(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from custom_components.omnibattery.control import temperature_limit as module
    coord=_Coord(data={'internal_temperature':55})
    stamp=datetime.now(timezone.utc)
    coord._key_update_times={'internal_temperature':stamp}
    clock=[0.0]
    monkeypatch.setattr(module.time,'monotonic',lambda:clock[0])
    mgr=_mgr(coords=[coord])
    assert mgr.apply_temperature_limit(coord,2500)==1000
    coord._key_update_times['internal_temperature']=stamp-timedelta(seconds=90)
    clock[0]=90
    assert mgr.apply_temperature_limit(coord,2500)==1000
    assert mgr.get_status()['bat']['telemetry_status']=='held'
    clock[0]=301
    assert mgr.apply_temperature_limit(coord,2500)==2500
    assert mgr.get_status()['bat']['telemetry_status']=='unavailable'


def test_cool_reading_does_not_cache_soc_cap():
    coord=_Coord(data={'internal_temperature':35})
    mgr=_mgr(coords=[coord])
    assert mgr.apply_temperature_limit(coord,200)==200
    coord.data['internal_temperature']=None
    assert mgr.apply_temperature_limit(coord,2500)==2500
