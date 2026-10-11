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


def test_planner_efficiency_uses_dispatch_eligibility():
    from custom_components.omnibattery.pricing.engine import PricingManager
    healthy=battery(BatteryEnergyModel(.95,.9))
    offline=battery(BatteryEnergyModel(.6,.8))
    requested=[]
    def available(*,is_charging):
        requested.append(is_charging)
        return [healthy]
    manager=PricingManager(None,SimpleNamespace(_get_available_batteries=available))
    assert manager._charge_efficiency_bound([healthy,offline])==.95
    assert requested==[True]
