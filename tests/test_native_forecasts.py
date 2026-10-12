from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from custom_components.omnibattery.forecast_providers import adapt_native_forecast
from custom_components.omnibattery.solar_forecast import read_remaining_solar_kwh, _extract_forecast_periods


def solcast(*rows):
    return {'detailedForecast':list(rows)}


def test_solcast_power_is_integrated_over_actual_duration():
    result = adapt_native_forecast(solcast(
        {'period_start':'2026-10-11T10:00:00Z','pv_estimate':2},
        {'period_end':'2026-10-11T11:30:00Z','period':'PT1H','pv_estimate':3}))
    assert result.source == 'solcast' and result.reason is None
    assert [p[2] for p in result.periods] == [1,3]


def test_forecast_solar_energy_is_interval_ending_wh():
    result = adapt_native_forecast({'timezone':'Europe/Amsterdam','result':{'watt_hours_period':{
        '2026-10-11 10:00:00':0, '2026-10-11 11:00:00':1500, '2026-10-11 12:00:00':2500}}})
    assert [p[2] for p in result.periods] == [1.5,2.5]
    assert result.periods[0][0].hour == 8


def test_forecast_solar_watts_are_trapezoidal_not_period_energy():
    result = adapt_native_forecast({'result':{'watts':{
        '2026-10-11T10:00:00Z':0, '2026-10-11T10:30:00Z':2000, '2026-10-11T11:00:00Z':4000}}})
    assert [p[2] for p in result.periods] == [.5,1.5]


def test_first_energy_interval_requires_a_start_or_explicit_duration():
    payload = {'result':{'watt_hours_period':{'2026-10-11T11:00:00Z':2000}}}
    assert adapt_native_forecast(payload).reason
    payload['period_minutes'] = 30
    result = adapt_native_forecast(payload)
    assert result.periods[0][0].minute == 30 and result.periods[0][2] == 2


@pytest.mark.parametrize('stamp', ['2026-10-25T02:00:00','2026-03-29T02:00:00'])
def test_ambiguous_and_nonexistent_native_local_times_are_rejected(stamp):
    payload=solcast({'period_start':stamp,'pv_estimate':2})
    payload['timezone']='Europe/Amsterdam'
    assert adapt_native_forecast(payload).reason


def test_explicit_dst_folds_remain_distinct():
    result=adapt_native_forecast(solcast(
        {'period_start':'2026-10-25T02:00:00+02:00','period':'PT1H','pv_estimate':1},
        {'period_start':'2026-10-25T02:00:00+01:00','period':'PT1H','pv_estimate':2}))
    assert [p[2] for p in result.periods]==[1,2]
    assert result.periods[1][0]-result.periods[0][0]==timedelta(hours=1)


@pytest.mark.parametrize('rows', [
    [{'period_start':'2026-10-11T10:00:00Z','pv_estimate':float('nan')}],
    [{'period_start':'2026-10-11T10:00:00Z','pv_estimate':-1}],
    [{'period_start':'2026-10-11T10:00:00','pv_estimate':2}],
    [{'period_start':'2026-10-11T10:00:00Z','pv_estimate':1}]*2,
    [{'period_start':'2026-10-11T11:00:00Z','pv_estimate':1},{'period_start':'2026-10-11T10:00:00Z','pv_estimate':1}],
    [{'period_start':'2026-10-11T10:00:00Z','pv_estimate':1},{'period_start':'2026-10-11T11:00:00Z','pv_estimate':1}],
])
def test_malformed_native_curves_fall_back_explicitly(rows):
    curve=adapt_native_forecast(solcast(*rows))
    assert not curve.periods and curve.reason=='invalid_solcast_periods'


def test_duplicate_instants_in_forecast_solar_are_rejected():
    curve=adapt_native_forecast({'result':{'watts':{'2026-10-11T10:00:00Z':1,'2026-10-11T12:00:00+02:00':2}}})
    assert curve.reason


def test_generic_energy_periods_reject_overlaps():
    period={'start':'2026-10-11T10:00:00Z','end':'2026-10-11T11:00:00Z','energy_kwh':2}
    assert not _extract_forecast_periods(SimpleNamespace(attributes={'periods':[period,period]}))


def test_native_curve_provenance_and_scalar_budget_reach_planner():
    from custom_components.omnibattery.pricing.solar_timeline import build_solar_timeline
    now=datetime(2026,10,11,10,tzinfo=timezone.utc)
    state=SimpleNamespace(state='3',last_reported=now,attributes={'unit_of_measurement':'kWh',**solcast(
        {'period_start':now,'period':'PT1H','pv_estimate':4})})
    hass=SimpleNamespace(states=SimpleNamespace(get=lambda _:state))
    ctrl=SimpleNamespace(solar_forecast_remaining_sensor='sensor.remaining')
    reading=read_remaining_solar_kwh(hass,ctrl,now=now)
    assert reading.remaining_kwh==3 and reading.curve_source=='solcast'
    assert reading.curve_fallback_reason is None
    timeline=build_solar_timeline([(now,now+timedelta(hours=1))],3,provider_periods=reading.periods,
                                 solar_start=now,solar_end=now+timedelta(hours=1))
    assert sum(timeline.intervals_kwh)==pytest.approx(3)
    state.attributes['detailedForecast'][0]['pv_estimate']=-1
    reading=read_remaining_solar_kwh(hass,ctrl,now=now)
    assert reading.remaining_kwh==3 and not reading.periods
    assert reading.curve_fallback_reason=='invalid_solcast_periods'
