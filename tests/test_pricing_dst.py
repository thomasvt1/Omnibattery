"""Price instants must survive provider parsing and legacy controller boundaries."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from homeassistant.util import dt as dt_util
from custom_components.omnibattery.pricing import calculations, PriceSlot, DynamicPricingSchedule
from custom_components.omnibattery.pricing.chronological import allocate_price_slots
from custom_components.omnibattery.pricing.engine import PricingManager
from custom_components.omnibattery.pricing.time_math import instant, local_time


@pytest.mark.parametrize('start,end', [
    ('2026-10-25T02:00:00+02:00','2026-10-25T02:00:00+01:00'),
    ('2026-03-29T01:00:00+01:00','2026-03-29T03:00:00+02:00'),
])
@pytest.mark.parametrize('provider', ['nordpool','ckw','epex','zonneplan'])
def test_dst_period_is_one_actual_hour(monkeypatch,start,end,provider):
    monkeypatch.setattr(dt_util,'DEFAULT_TIME_ZONE',ZoneInfo('Europe/Madrid'))
    attrs = {
        'nordpool': {'raw_today':[dict(start=start,end=end,value=.1)]},
        'ckw': {'prices':[dict(start=start,end=end,price=.1)]},
        'epex': {'data':[dict(start_time=start,end_time=end,price_per_kwh=.1)]},
        'zonneplan': {'forecast':[dict(start_date=start,end_date=end,price_tax_included={'amount':1000000})]},
    }[provider]
    slot=calculations.parse_prices_for_integration(provider,attrs)[0]
    assert slot.start.tzinfo == timezone.utc
    assert slot.end-slot.start == timedelta(hours=1)
    now=local_time(slot.start).replace(tzinfo=None)
    plan=allocate_price_slots([],[],[slot],total_required_kwh=2,effective_power_kw=1,
                              now=now,horizon_end=slot.end,charge_efficiency=1)
    assert plan.allocated_kwh == pytest.approx(1)
    assert calculations.select_cheapest_slots_by_duration([slot],1,None,now=now)==[slot]


def test_repeated_hour_periods_are_distinct(monkeypatch):
    monkeypatch.setattr(dt_util,'DEFAULT_TIME_ZONE',ZoneInfo('Europe/Madrid'))
    slots=calculations.parse_nordpool_prices({'raw_today':[
        dict(start='2026-10-25T02:00:00+02:00',end='2026-10-25T02:00:00+01:00',value=.1),
        dict(start='2026-10-25T02:00:00+01:00',end='2026-10-25T03:00:00+01:00',value=.2),
    ]})
    assert len(set(slots))==2
    assert slots[0].end==slots[1].start
    assert instant(datetime(2026,10,25,2,30,fold=1)) > slots[0].end
    assert local_time(slots[1].start).hour==2


def test_local_price_release_and_consumption_cross_midnight(monkeypatch):
    from custom_components.omnibattery.control.charge_delay import ChargeDelayManager
    from custom_components.omnibattery.pricing.discharge_reserve import consumption_by_slot
    monkeypatch.setattr(dt_util, 'DEFAULT_TIME_ZONE', ZoneInfo('Europe/Madrid'))
    start = datetime(2026, 7, 5, 22, tzinfo=timezone.utc)  # Monday 00:00 local
    slot = PriceSlot(start, start + timedelta(hours=1), .1)
    ctrl = SimpleNamespace(price_sensor='sensor.price', predictive_charging_enabled=True,
        predictive_charging_mode='dynamic_pricing',
        _pricing_mgr=SimpleNamespace(get_future_price_slots=lambda: [slot]))
    manager = object.__new__(ChargeDelayManager)
    manager._controller = ctrl
    assert manager._price_optimal_release_h(0, 2) == 0
    assert manager._window_avg_price(0, 1, [slot]) == pytest.approx(.1)
    assert consumption_by_slot([slot], {local_time(start).date(): [1]*96})[slot] == 4
    window = dict(enabled=True, days=['mon'], start_time='00:00', end_time='01:00')
    assert PricingManager._future_slot_matches_operation_block(slot, window)
    assert not PricingManager._future_slot_matches_operation_block(slot, {**window, 'days':['sun']})


def test_consumption_repeated_hour_uses_local_bins_twice(monkeypatch):
    from custom_components.omnibattery.pricing.discharge_reserve import consumption_by_slot
    monkeypatch.setattr(dt_util, 'DEFAULT_TIME_ZONE', ZoneInfo('Europe/Madrid'))
    start = datetime(2026, 10, 25, 0, tzinfo=timezone.utc)
    slot = PriceSlot(start, start + timedelta(hours=2), .1)
    profile = [0]*96
    profile[8:12] = [1]*4
    assert consumption_by_slot([slot], {}, profile)[slot] == 8


def test_price_release_keeps_second_fold_pending(monkeypatch):
    from custom_components.omnibattery.control import charge_delay as module
    monkeypatch.setattr(dt_util, 'DEFAULT_TIME_ZONE', ZoneInfo('Europe/Madrid'))
    first=datetime(2026,10,25,0,tzinfo=timezone.utc)
    slots=[PriceSlot(first, first+timedelta(hours=1), .4),
           PriceSlot(first+timedelta(hours=1), first+timedelta(hours=2), .1)]
    monkeypatch.setattr(module, '_decision_now', lambda:local_time(first))
    mgr=object.__new__(module.ChargeDelayManager)
    mgr._controller=SimpleNamespace(price_sensor='sensor.price',predictive_charging_enabled=True,
        predictive_charging_mode='dynamic_pricing',
        _pricing_mgr=SimpleNamespace(get_future_price_slots=lambda:slots))
    assert mgr._window_avg_price(first,1,slots)==pytest.approx(.4)
    assert mgr._window_avg_price(first+timedelta(hours=1),1,slots)==pytest.approx(.1)
    assert mgr._window_avg_price(first,2,slots)==pytest.approx(.25)
    for duration in (None,1):
        assert mgr._price_optimal_release_h(2,4,duration)==2
        assert mgr._price_release_pending(2,2)
    monkeypatch.setattr(module, '_decision_now',lambda:local_time(first+timedelta(hours=1)))
    assert mgr._price_optimal_release_h(2,4,1)==2
    assert not mgr._price_release_pending(2,2)
