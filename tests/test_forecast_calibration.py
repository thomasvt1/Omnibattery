from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import copy
import pytest
from custom_components.omnibattery.tracking.forecast_calibration import ForecastCalibration


def day(journal, start, power=1, **kwargs):
    assert journal.issue('provider', start, 8)
    end = datetime.combine(start.date() + timedelta(days=1), datetime.min.time(), start.tzinfo)
    stamp = start.timestamp()
    while stamp <= end.timestamp():
        journal.observe(datetime.fromtimestamp(stamp, timezone.utc), power, **kwargs)
        stamp += 120


def test_issuance_is_immutable_and_evaluation_matches_horizon():
    j = ForecastCalibration()
    now = datetime(2026, 10, 1, 18, tzinfo=timezone.utc)
    assert j.issue('provider', now, 8)
    assert not j.issue('provider', now + timedelta(hours=1), 100)
    for minute in range(361):
        j.observe(now + timedelta(minutes=minute), 1)
    assert j.outcomes[0]['forecast_kwh'] == 8
    assert j.outcomes[0]['actual_kwh'] == pytest.approx(6)
    assert j.outcomes[0]['scored']
    assert j.stats('provider', now + timedelta(days=1))['reserve_fraction'] == 0


@pytest.mark.parametrize('mode', ['missing', 'gap', 'curtailed', 'restart'])
def test_missing_or_censored_horizon_never_scores_as_zero(mode):
    j = ForecastCalibration()
    now = datetime(2026, 10, 1, 18, tzinfo=timezone.utc)
    j.issue('provider', now, 8)
    for minute in range(361):
        if minute == 150:
            if mode == 'restart':
                saved = j.dump(); j = ForecastCalibration(); j.restore(saved)
            elif mode == 'gap':
                continue
        if mode == 'gap' and minute == 151:
            continue
        j.observe(now + timedelta(minutes=minute), None if mode == 'missing' else 0,
                  censored=mode == 'curtailed')
    assert not j.outcomes[0]['scored']
    assert j.stats('provider', now + timedelta(days=1))['samples'] == 0


def test_calibration_is_bounded_causal_and_source_and_bucket_specific():
    j = ForecastCalibration()
    now = datetime(2026, 9, 1, 18, tzinfo=timezone.utc)
    for n in range(10):
        day(j, now + timedelta(days=n), power=.5)
    assert j.stats('provider', now + timedelta(days=9))['samples'] == 9
    stats = j.stats('provider', now + timedelta(days=10))
    assert stats['samples'] == 10 and stats['reserve_fraction'] == .30
    assert stats['bias_kwh'] == pytest.approx(5)
    assert j.stats('other', now + timedelta(days=10))['samples'] == 0
    assert j.stats('provider', (now + timedelta(days=10)).replace(hour=12))['samples'] == 0
    saved = j.dump(); restored = ForecastCalibration(); restored.restore(saved)
    assert restored.stats('provider', now + timedelta(days=10)) == stats
    assert j.stats('provider', now + timedelta(days=110))['samples'] == 0


@pytest.mark.parametrize('month,day_number,expected_hours', [(3,29,23), (10,25,25)])
def test_horizons_follow_local_midnight_across_dst(month, day_number, expected_hours):
    j = ForecastCalibration()
    now = datetime(2026, month, day_number, tzinfo=ZoneInfo('Europe/Amsterdam'))
    day(j, now)
    assert j.outcomes[0]['actual_kwh'] == pytest.approx(expected_hours)
    assert j.outcomes[0]['scored']


def test_invalid_persisted_evidence_is_discarded():
    j = ForecastCalibration(); now = datetime(2026, 10, 1, 18, tzinfo=timezone.utc)
    day(j, now)
    saved = j.dump()
    for key, value in [('forecast_kwh', float('nan')), ('covered_s', -1), ('source', []), ('day','bad')]:
        bad = copy.deepcopy(saved); bad['outcomes'][0][key] = value
        restored = ForecastCalibration(); restored.restore(bad)
        assert restored.outcomes == []


def test_read_only_adapter_applies_reserve_without_issuing(monkeypatch):
    from custom_components.omnibattery import solar_forecast as module
    j = ForecastCalibration(); now = datetime(2026, 9, 1, 18, tzinfo=timezone.utc)
    for n in range(10):
        day(j, now + timedelta(days=n))
    for r in j.outcomes:
        r['source'] = 'sensor.pv:remaining_sensor:none'
    current = now + timedelta(days=10)
    period = module.SolarForecastPeriod(current, current + timedelta(hours=1), 8)
    monkeypatch.setattr(module, '_read_remaining_solar_kwh', lambda *a, **kw:
        module.SolarForecastInput(8, 'remaining_sensor', original_source='remaining', periods=(period,), freshness='fresh'))
    monkeypatch.setattr(module, 'get_configured_solar_forecast_sensor', lambda *a: 'sensor.pv')
    ctrl = SimpleNamespace(_consumption_tracker=SimpleNamespace(forecast_calibration=j))
    before = j.dump()
    reading = module.read_remaining_solar_kwh(SimpleNamespace(), ctrl, now=current, update_controller=False)
    assert reading.remaining_kwh == pytest.approx(6)
    assert reading.raw_remaining_kwh == 8 and reading.uncertainty_kwh == pytest.approx(2)
    assert reading.periods[0].energy_kwh == pytest.approx(6)
    assert j.dump() == before and not hasattr(ctrl, 'solar_forecast_calibration')
    assert module.read_remaining_solar_kwh(SimpleNamespace(), ctrl, now=current).remaining_kwh == reading.remaining_kwh
    assert j.pending[0]['forecast_kwh'] == 8


def test_fresh_complete_production_required():
    from custom_components.omnibattery.tracking.consumption_tracker import ConsumptionTracker
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    state = SimpleNamespace(last_reported=now)
    coord = SimpleNamespace(capabilities=SimpleNamespace(has_solar_telemetry=True),
        data={'solar_power': 1000}, _key_update_times={'solar_power':now}, is_available=True)
    tracker = object.__new__(ConsumptionTracker)
    tracker._controller = SimpleNamespace(solar_production_sensor='sensor.pv', coordinators=[coord])
    tracker._hass = SimpleNamespace(states=SimpleNamespace(get=lambda _:state))
    tracker._read_power_kw = lambda _: 2
    assert tracker._calibration_solar_power_kw(now) == 3
    coord.is_available = False
    assert tracker._calibration_solar_power_kw(now) is None
    coord.is_available = True; coord._key_update_times['solar_power'] = now - timedelta(seconds=121)
    assert tracker._calibration_solar_power_kw(now) is None
    coord._key_update_times['solar_power'] = now; state.last_reported = now - timedelta(seconds=121)
    assert tracker._calibration_solar_power_kw(now) is None


@pytest.mark.asyncio
async def test_history_restores_even_when_daily_totals_are_from_yesterday():
    from custom_components.omnibattery.tracking.consumption_tracker import ConsumptionTracker
    j = ForecastCalibration()
    day(j, datetime(2026, 9, 1, 18, tzinfo=timezone.utc))
    async def load():
        return {'date': '2000-01-01', 'forecast_calibration': j.dump()}
    tracker = object.__new__(ConsumptionTracker)
    tracker._controller = SimpleNamespace()
    tracker._daily_energy_store = SimpleNamespace(async_load=load)
    tracker.forecast_calibration = ForecastCalibration()
    await tracker.load_daily_energy()
    assert tracker.forecast_calibration.dump() == j.dump()
    assert not vars(tracker._controller)


@pytest.mark.asyncio
async def test_runtime_records_missing_production_and_curtailment(monkeypatch):
    from custom_components.omnibattery.tracking.consumption_tracker import ConsumptionTracker
    tracker = object.__new__(ConsumptionTracker)
    calls = []
    tracker.forecast_calibration = SimpleNamespace(observe=lambda *a, **kw: calls.append((a,kw)))
    tracker._solar_runtime_context = lambda _: {'explicit_curtailment': True, 'battery_full_risk':False, 'export_zero':False}
    tracker._calibration_solar_power_kw = lambda _: None
    tracker._read_total_solar_power_kw = lambda: None
    tracker._solar_profile = SimpleNamespace(mode='off')
    await tracker.accumulate_daily_solar_energy()
    assert calls[0][0][1] is None
    assert calls[0][1] == {'censored':True}
