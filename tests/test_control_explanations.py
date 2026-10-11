from types import SimpleNamespace
from custom_components.omnibattery.control.explanations import battery_explanations

def test_explanation_preserves_unknown_release_and_observed_command():
    battery=SimpleNamespace(device_key='b',is_available=True,battery_manual_mode_enabled=True,
                            commanded_charge_power=500,commanded_discharge_power=0)
    controller=SimpleNamespace(coordinators=[battery],get_charge_blockers=lambda _: {},
                               get_discharge_blockers=lambda _: {'reserve':{'reason':'Saving energy'}})
    result=battery_explanations(controller)['b']
    assert result['owner']=='manual'
    assert result['commanded_power_w']==500
    assert result['blockers']['discharge']==['Saving energy']
    assert result['release_times']==[]
    assert result['charge_ceiling_w'] is None


def test_disconnected_command_is_unknown_and_known_delay_is_exposed():
    battery=SimpleNamespace(device_key='b',is_available=False,
                            commanded_charge_power=500,commanded_discharge_power=0)
    controller=SimpleNamespace(coordinators=[battery],
        get_charge_blockers=lambda _: {'charge_delay':{'details':{'state':'Delayed'}}},
        _charge_delay_status={'estimated_unlock_time':'13:30'})
    result=battery_explanations(controller)['b']
    assert result['owner']=='unknown'
    assert result['commanded_power_w'] is None
    assert result['release_times']==['13:30']
