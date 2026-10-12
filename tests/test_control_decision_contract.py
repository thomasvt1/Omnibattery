from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from custom_components.omnibattery import ChargeDischargeController
from custom_components.omnibattery.control.decision import ControlInputs, decide_control, apply_phase_limits
from tests.test_set_battery_power_skip import _controller, _Coord, _ok


def test_inputs_and_decisions_are_immutable_and_copy_blocker_sequences():
    blocks=['ev_pause']
    inputs=ControlInputs(500,0,charge_blockers=blocks)
    blocks.clear()
    decision=decide_control(inputs)
    assert decision.charge_power_w==0 and decision.reasons==('charge:ev_pause',)
    with pytest.raises(FrozenInstanceError): decision.charge_power_w=1000


@pytest.mark.parametrize('powers', [(float('nan'),0),(float('inf'),0),(-1,0),(5,5),(0,float('nan'))])
async def test_invalid_requests_never_reach_the_driver(powers):
    ctrl=_controller(); coord=_Coord({})
    assert not await ChargeDischargeController._set_battery_power(ctrl,coord,*powers,force_write=True,bypass_blockers=True)
    coord.apply_power.assert_not_called()
    decision=ctrl._last_control_decisions[coord.device_key]
    assert decision['net_power_w'] is None and 'invalid_power_request' in decision['reasons']


@pytest.mark.parametrize('flag, reason', [('manual_owned','manual_owner'),('backup_owned','backup_owner'),
                                        ('external_owned','external_owner'),('slot_owned','manual_slot_owner')])
def test_ownership_veto_is_independent_of_power_caps(flag,reason):
    decision=decide_control(replace(ControlInputs(1000,0,charge_cap_w=500),**{flag:True}))
    assert not decision.allowed and reason in decision.reasons


async def test_forced_manual_commands_still_obey_caps_and_record_exact_intent():
    ctrl=_controller(); coord=_Coord({}); coord.max_charge_power=803
    coord.battery_manual_mode_enabled=True
    coord.apply_power=AsyncMock(return_value=_ok(803))
    ctrl.get_charge_blockers=lambda _: {'ev_pause':{}}
    assert await ChargeDischargeController._set_battery_power(ctrl,coord,900,0,
        owner='battery_manual',bypass_blockers=True,force_write=True)
    coord.apply_power.assert_awaited_once_with(803,read_back=True)
    record=ctrl._last_control_decisions[coord.device_key]
    assert record['net_power_w']==803 and record['requested_charge_w']==900
    assert record['evidence']=='validated_intent' and record['reasons']==('charge_cap',)


async def test_phase_limiter_cannot_increase_power_or_reverse_direction():
    ctrl=_controller(); coord=_Coord({})
    coord.apply_power=AsyncMock(return_value=_ok(500))
    ctrl._phase_power_limiter=SimpleNamespace(enabled=True,limit_single_command=lambda *args:(900,900))
    assert await ChargeDischargeController._set_battery_power(ctrl,coord,500,0,force_write=True)
    coord.apply_power.assert_awaited_once_with(500,read_back=True)
    assert ctrl._last_control_decisions[coord.device_key]['net_power_w']==500


async def test_phase_reduction_is_the_same_decision_the_driver_executes():
    ctrl=_controller(); coord=_Coord({})
    coord.apply_power=AsyncMock(return_value=_ok(-123))
    ctrl._phase_power_limiter=SimpleNamespace(enabled=True,limit_single_command=lambda *args:(0,123.9))
    assert await ChargeDischargeController._set_battery_power(ctrl,coord,0,500,force_write=True)
    coord.apply_power.assert_awaited_once_with(-123,read_back=True)
    assert ctrl._last_control_decisions[coord.device_key]['net_power_w']==-123
    assert 'phase_limit' in ctrl._last_control_decisions[coord.device_key]['reasons']


def test_bad_caps_and_phase_outputs_are_finite_and_conservative():
    decision=decide_control(ControlInputs(500,0,charge_cap_w=float('nan')))
    assert decision.charge_power_w==0
    valid=decide_control(ControlInputs(0,500,discharge_cap_w=450.9))
    assert valid.discharge_power_w==450
    assert apply_phase_limits(valid,0,float('nan')).net_power_w==0


async def test_ignored_blockers_do_not_bypass_other_blockers():
    ctrl=_controller(); coord=_Coord({})
    coord.apply_power=AsyncMock(return_value=_ok(0))
    ctrl.get_charge_blockers=lambda _: {'price':{},'ev_pause':{}}
    assert await ChargeDischargeController._set_battery_power(ctrl,coord,500,0,
        ignore_charge_blockers={'price'},force_write=True)
    coord.apply_power.assert_awaited_once_with(0,read_back=True)
    assert ctrl._last_control_decisions[coord.device_key]['reasons']==('charge:ev_pause',)


async def test_unknown_owner_cannot_bypass_automatic_ownership_guards():
    ctrl = _controller()
    coord = _Coord({})
    coord.battery_manual_mode_enabled = True
    assert not await ChargeDischargeController._set_battery_power(
        ctrl, coord, 500, 0, owner="automatic_typo",
        force_write=True, bypass_blockers=True)
    coord.apply_power.assert_not_called()
    assert "invalid_owner" in ctrl._last_control_decisions[coord.device_key]["reasons"]
