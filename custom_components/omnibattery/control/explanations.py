"""Read-only battery control evidence shared by entities and diagnostics."""
import math


def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def battery_explanations(controller):
    result = {}
    for battery in controller.coordinators:
        if getattr(battery, "battery_manual_mode_enabled", False):
            owner = "manual"
        elif getattr(battery, "rs485_user_disabled", False):
            owner = "external"
        elif getattr(controller, "_is_backup_function_active", lambda _: False)(battery):
            owner = "backup"
        elif getattr(controller, "_is_manual_slot_owned", lambda _: False)(battery):
            owner = "manual_slot"
        else:
            owner = "automatic"
        blocks = {}
        releases = []
        for direction in ("charge", "discharge"):
            getter = getattr(controller, f"get_{direction}_blockers", lambda _: {})
            records = getter(battery)
            blocks[direction] = [str(record.get("reason") or key) if isinstance(record, dict) else str(key)
                                 for key, record in records.items()]
            for record in records.values():
                details = record.get("details", {}) if isinstance(record, dict) else {}
                for key in ("release_at", "next_release_at", "until"):
                    stamp = details.get(key)
                    if stamp is not None:
                        releases.append(stamp.isoformat() if hasattr(stamp, "isoformat") else str(stamp))
        charge = _number(getattr(battery, "commanded_charge_power", None))
        discharge = _number(getattr(battery, "commanded_discharge_power", None))
        result[str(battery.device_key)] = {
            "owner": owner,
            "commanded_power_w": charge - discharge if charge is not None and discharge is not None else None,
            "charge_ceiling_w": _number(getattr(battery, "effective_max_charge_power", None)),
            "discharge_ceiling_w": _number(getattr(battery, "effective_max_discharge_power", None)),
            "blockers": blocks,
            "release_times": sorted(set(releases)),
            "available": bool(battery.is_available),
        }
    return result
