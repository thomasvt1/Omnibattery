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
    dict(samples=2),dict(duration_s=10),dict(isolated_converter=False),
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
