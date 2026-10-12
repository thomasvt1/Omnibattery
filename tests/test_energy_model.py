from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from custom_components.omnibattery.energy_model import (
    BatteryEnergyModel, EfficiencyMeasurement, battery_energy_model, fleet_charge_efficiency,
)
from custom_components.omnibattery.control.charge_order import time_to_full_h, charge_allocation_weights
from custom_components.omnibattery.pricing import PriceSlot
from custom_components.omnibattery.pricing.chronological import ChronologicalEvaluationRequest, evaluate_chronological_request


def battery(model, evidence=None):
    class Battery:
        capabilities=SimpleNamespace(energy_model=model)
        driver=SimpleNamespace(efficiency_measurements=evidence or {})
        battery_capacity_kwh=10
        max_soc=100
        data={'battery_soc':50}
    return Battery()


def test_mixed_models_keep_direction_and_finish_times_separate():
    a=battery(BatteryEnergyModel(.8,.9,1100,900,'driver'))
    b=battery(BatteryEnergyModel(.95,.8,1800,1400,'driver'))
    ctrl=SimpleNamespace(_battery_power_limit=lambda *_:1000)
    assert time_to_full_h(ctrl,a)==pytest.approx(6.25)
    assert time_to_full_h(ctrl,b)==pytest.approx(5/.95)
    weights=charge_allocation_weights([a,b],{a:1000,b:1000})
    assert weights[a]/weights[b]==pytest.approx(.95/.8)
    assert fleet_charge_efficiency([a,b])==.8
    assert battery_energy_model(a).round_trip_efficiency==pytest.approx(.72)
    now=datetime(2026,10,11,tzinfo=timezone.utc)
    request=ChronologicalEvaluationRequest(now,now+timedelta(hours=1),(),
        (PriceSlot(now,now+timedelta(hours=1),.1),),2,1,charge_efficiency=.8)
    assert evaluate_chronological_request(request).plan.allocated_kwh==pytest.approx(.8)


@pytest.mark.parametrize('change', [dict(input_kwh=0),dict(output_kwh=float('nan')),
    dict(samples=2),dict(samples=float('inf')),dict(samples=30.5),dict(duration_s=10),dict(isolated_converter=False),
    dict(observed_at=datetime(2020,1,1,tzinfo=timezone.utc)),dict(observed_at=datetime(2026,10,11))])
def test_invalid_measurement_falls_back(change):
    now=datetime(2026,10,11,tzinfo=timezone.utc)
    values=dict(input_kwh=1,output_kwh=.93,duration_s=600,samples=60,observed_at=now,isolated_converter=True)
    valid=EfficiencyMeasurement(**values)
    assert battery_energy_model(battery(BatteryEnergyModel(),{'charge':valid}),now).charge_efficiency==.93
    values.update(change)
    result=battery_energy_model(battery(BatteryEnergyModel(),{'charge':EfficiencyMeasurement(**values)}),now)
    assert result.charge_efficiency==.85
    assert result.source=='legacy_assumption'


@pytest.mark.parametrize('value',[0,1.1,float('nan'),float('inf')])
def test_invalid_driver_efficiency_rejected(value):
    with pytest.raises(ValueError): BatteryEnergyModel(charge_efficiency=value)


def test_planner_efficiency_uses_future_eligibility():
    from custom_components.omnibattery.pricing.engine import PricingManager
    healthy=battery(BatteryEnergyModel(.95,.9))
    offline=battery(BatteryEnergyModel(.6,.8))
    healthy.is_available=True
    offline.is_available=False
    manager=PricingManager(None,SimpleNamespace(
        _get_available_batteries=lambda **kw: [],  # temporary EV charge pause
        get_charge_blockers=lambda _: {"ev_pause":{}},
    ))
    assert manager._charge_efficiency_bound([healthy,offline])==.95
    healthy.capabilities=SimpleNamespace(energy_model=BatteryEnergyModel(.6,.8))
    assert manager._charge_efficiency_bound([healthy])==.6
    healthy.is_available=False
    assert manager._charge_efficiency_bound([healthy])==.6


@pytest.mark.parametrize('attribute', ['battery_manual_mode_enabled','rs485_user_disabled'])
def test_owned_battery_does_not_reduce_healthy_model(attribute):
    from custom_components.omnibattery.pricing.engine import PricingManager
    healthy=battery(BatteryEnergyModel(.95,.9))
    excluded=battery(BatteryEnergyModel(.6,.8))
    setattr(excluded,attribute,True)
    manager=PricingManager(None,SimpleNamespace())
    assert manager._charge_efficiency_bound([healthy,excluded])==.95


@pytest.mark.parametrize('attribute,value', [('allow_charge',False),('effective_max_charge_power',0),
    ('max_charge_power',0),('effective_max_charge_power',float('nan'))])
def test_permanently_charge_disabled_battery_is_excluded(attribute,value):
    from custom_components.omnibattery.pricing.engine import PricingManager
    healthy=battery(BatteryEnergyModel(.95,.9))
    disabled=battery(BatteryEnergyModel(.6,.8))
    setattr(disabled,attribute,value)
    manager=PricingManager(None,SimpleNamespace())
    assert manager._charge_efficiency_bound([healthy,disabled])==.95


def test_legacy_duration_and_charge_delay_use_directional_efficiency():
    from custom_components.omnibattery.pricing.calculations import calculate_exact_charging_hours_needed
    from custom_components.omnibattery.control.charge_delay import _charge_time_h
    assert calculate_exact_charging_hours_needed(6,1000,1000,charge_efficiency=.6)==10
    c=battery(BatteryEnergyModel(.6,.9))
    c.data={'battery_soc':40,'battery_total_energy':10}
    ctrl=SimpleNamespace(_battery_power_limit=lambda *_:1000)
    assert _charge_time_h(ctrl,[c],100,6,1)==10


def test_future_model_read_does_not_mutate_nonresponsive_cooldowns():
    from custom_components.omnibattery.energy_model import future_charge_efficiency
    healthy=battery(BatteryEnergyModel(.95,.9));healthy.name='healthy'
    excluded=battery(BatteryEnergyModel(.6,.8));excluded.name='offline'
    def mutating_query(_):
        raise AssertionError('read-only model lookup must not reset cooldowns')
    ctrl=SimpleNamespace(coordinators=[healthy,excluded],
        _non_responsive=SimpleNamespace(excluded_names=lambda:['offline'],is_excluded=mutating_query))
    assert future_charge_efficiency(ctrl)==.95


def test_future_model_uses_identity_and_does_not_reset_expired_exclusions():
    from homeassistant.util import dt as dt_util
    from custom_components.omnibattery.energy_model import future_charge_efficiency
    from custom_components.omnibattery.tracking.non_responsive_tracker import NonResponsiveTracker
    healthy=battery(BatteryEnergyModel(.95,.9));healthy.name='same name'
    excluded=battery(BatteryEnergyModel(.6,.8));excluded.name='same name'
    tracker=NonResponsiveTracker()
    tracker.batteries[excluded]={'excluded_at':dt_util.utcnow(),'fail_count':3,'wake_used':True}
    ctrl=SimpleNamespace(coordinators=[healthy,excluded],_non_responsive=tracker)
    assert future_charge_efficiency(ctrl)==.95
    tracker.batteries[excluded]['excluded_at']-=timedelta(minutes=6)
    before=dict(tracker.batteries[excluded])
    assert future_charge_efficiency(ctrl)==.6
    assert tracker.batteries[excluded]==before


def test_dashboard_projection_uses_each_battery_directional_efficiency():
    from custom_components.omnibattery import ChargeDischargeController
    a = battery(BatteryEnergyModel(.6, .95))
    b = battery(BatteryEnergyModel(.9, .7))
    for device in (a, b):
        device.data = {"battery_soc": 50, "battery_total_energy": 10}
        device.max_charge_power = device.max_discharge_power = 1000
    controller = SimpleNamespace(
        coordinators=[a, b], _is_battery_manual_owned=lambda _: False,
        _daily_operation_float=ChargeDischargeController._daily_operation_float,
    )
    snapshots = ChargeDischargeController._daily_operation_battery_inputs(controller)
    assert [(s.charge_efficiency, s.discharge_efficiency) for s in snapshots] == [(.6, .95), (.9, .7)]


def test_chronological_deadlines_require_stored_energy_for_ac_demand():
    from custom_components.omnibattery.pricing.chronological import EnergyInterval
    now = datetime(2026, 10, 11, tzinfo=timezone.utc)
    end = now + timedelta(hours=1)
    request = ChronologicalEvaluationRequest(now, end,
        (EnergyInterval(now, end, 4.5, 0),), (PriceSlot(now,end,.1),),
        2.5, 4, headroom_kwh=5, usable_initial_kwh=5, charge_efficiency=.8, discharge_efficiency=.6)
    plan = evaluate_chronological_request(request).plan
    assert plan.ac_intervals[0].consumption_kwh == 4.5
    assert plan.intervals[0].consumption_kwh == pytest.approx(7.5)
    assert plan.deadline_required_kwh == pytest.approx(2.5)
    assert plan.allocated_kwh == pytest.approx(2.5)


def test_chronological_pv_serves_simultaneous_load_before_conversion():
    from custom_components.omnibattery.pricing.chronological import EnergyInterval, stored_energy_intervals
    now = datetime(2026, 10, 11, tzinfo=timezone.utc)
    intervals = stored_energy_intervals((EnergyInterval(now,now+timedelta(hours=1),1,5),),.6,.5)
    assert intervals[0].consumption_kwh == 0
    assert intervals[0].solar_kwh == pytest.approx(2.4)


def test_absorption_efficiency_excludes_hard_discharge_blocks():
    from custom_components.omnibattery.pricing.curtailment import BatterySnapshot, snapshot_discharge_efficiency
    healthy = BatterySnapshot('healthy',50,10,100,10,2500,True,True,.95)
    blocked = BatterySnapshot('blocked',50,10,100,10,2500,True,False,.6)
    assert snapshot_discharge_efficiency([healthy,blocked]) == .95


def test_headroom_bounds_maximum_stored_pv_but_charge_credit_stays_minimum():
    from custom_components.omnibattery.energy_model import future_charge_efficiency
    low = battery(BatteryEnergyModel(.6, .8))
    high = battery(BatteryEnergyModel(.9, .8))
    ctrl = SimpleNamespace(coordinators=[low, high])
    assert future_charge_efficiency(ctrl) == .6
    assert future_charge_efficiency(ctrl, for_headroom=True) == .9
    high.allow_charge = False
    assert future_charge_efficiency(ctrl, for_headroom=True) == .6


def test_runtime_curtailment_reserves_the_most_efficient_batterys_pv_footprint():
    from custom_components.omnibattery.pricing.engine import PricingManager
    from custom_components.omnibattery.pricing.curtailment import BatterySnapshot
    now = datetime(2026, 10, 12, 8, tzinfo=timezone.utc)
    slot = PriceSlot(now + timedelta(hours=1), now + timedelta(hours=2), -.1)
    ctrl = SimpleNamespace(
        coordinators=[battery(BatteryEnergyModel(.6, .8)), battery(BatteryEnergyModel(.9, .8))],
        max_charge_capacity=5000, solar_forecast_source="remaining")
    manager = PricingManager(None, ctrl)
    manager._smart_predischarge_enabled = lambda: True
    manager._curtailment_plan_slots = lambda slots, now: slots
    manager._curtailment_forecast_model = lambda now: (5, lambda hour: max(0, min(1, hour - 9)), 0)
    manager._curtailment_battery_snapshots = lambda: [
        BatterySnapshot("a", 50, 10, 100, 10, 2500),
        BatterySnapshot("b", 50, 10, 100, 10, 2500)]
    manager._curtailment_operation_blocked_slots = lambda slots: []
    manager._curtailment_export_settings = lambda: ("self_consumption", 0)
    manager._update_curtailment_opportunistic_diagnostics = lambda *args: None
    manager._set_curtailment_runtime = lambda *args: None
    plan = manager._build_curtailment_plan([slot], now=now)
    assert plan.status == "protected"
    assert plan.required_headroom_kwh == pytest.approx(4.5)
    assert plan.solar_reserve_by_slot[slot] == pytest.approx(4.5)
