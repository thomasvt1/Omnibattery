from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import pytest
from custom_components.omnibattery.solar_forecast import read_remaining_solar_kwh, forecast_freshness

NOW=datetime(2026,10,11,18,tzinfo=timezone.utc)


def test_stale_numeric_forecast_cannot_supply_solar_budget():
    state=SimpleNamespace(state='12',attributes={'unit_of_measurement':'kWh'},last_updated=NOW-timedelta(days=10))
    hass=SimpleNamespace(states=SimpleNamespace(get=lambda _:state),config=SimpleNamespace(time_zone='UTC'))
    ctrl=SimpleNamespace(solar_forecast_remaining_sensor='sensor.forecast',solar_forecast_sensor=None)
    result=read_remaining_solar_kwh(hass,ctrl,now=NOW)
    assert result.remaining_kwh==0
    assert result.fallback_reason=='stale'
    assert ctrl.solar_forecast_freshness=='stale'


def test_recent_report_of_unchanged_value_is_fresh():
    state=SimpleNamespace(attributes={},last_reported=NOW,last_updated=NOW-timedelta(days=10))
    assert forecast_freshness(state,NOW,ZoneInfo('UTC'))[0]=='fresh'


@pytest.mark.parametrize('attributes,expected',[
    ({'generated_at':(NOW-timedelta(days=1)).isoformat()},'stale'),
    ({'forecast_date':'2026-10-10'},'wrong_date'),
    ({'forecast_date':'invalid'},'invalid_date'),
    ({'generated_at':(NOW+timedelta(hours=1)).isoformat()},'future_timestamp'),
])
def test_provider_validity_wins_over_recent_ha_report(attributes,expected):
    state=SimpleNamespace(attributes=attributes,last_reported=NOW)
    assert forecast_freshness(state,NOW,ZoneInfo('UTC'))[0]==expected


@pytest.mark.parametrize('issued', ['garbage', '2026-10-11T12:00:00', None])
def test_invalid_explicit_issuance_is_rejected(issued):
    state=SimpleNamespace(attributes={'generated_at':issued},last_reported=NOW)
    assert forecast_freshness(state,NOW,ZoneInfo('UTC'))[0]=='invalid_timestamp'


@pytest.mark.parametrize('fallback', [None, SimpleNamespace(state='unknown',attributes={},last_reported=NOW)])
def test_readonly_rejection_survives_unusable_legacy_fallback(fallback):
    stale=SimpleNamespace(state='12',attributes={},last_reported=NOW-timedelta(days=1))
    states={'sensor.remaining':stale,'sensor.today':fallback}
    hass=SimpleNamespace(states=SimpleNamespace(get=states.get),config=SimpleNamespace(time_zone='UTC'))
    ctrl=SimpleNamespace(solar_forecast_remaining_sensor='sensor.remaining',solar_forecast_sensor='sensor.today',
                         solar_forecast_freshness='fresh')
    result=read_remaining_solar_kwh(hass,ctrl,now=NOW,update_controller=False)
    assert result.fallback_reason=='stale'
    assert ctrl.solar_forecast_freshness=='fresh'
    from custom_components.omnibattery.pricing.engine import PricingManager
    mgr=PricingManager(hass,ctrl)
    mgr._read_remaining_solar_input=lambda **kwargs:result
    ctrl._dp_last_eval_solar_remaining_kwh=12
    assert mgr._read_remaining_solar_reading(NOW)==0
    assert mgr._is_solar_forecast_reeval(NOW)
