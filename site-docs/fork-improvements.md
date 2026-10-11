# Fork improvements

## Pricing time

Provider price intervals retain UTC timestamps. Legacy naive control times are
interpreted in Home Assistant's configured timezone; displays use local time.
Repeated daylight-saving hours remain separate intervals, and energy capacity
uses elapsed time rather than wall-clock subtraction.

## Forecast freshness

Forecast reports and explicit `generated_at` / `forecast_generated_at` timestamps
expire after six hours. An explicit `forecast_date` must match the current local
date; timestamps more than five minutes in the future are rejected. Repeated
reports of an unchanged value remain valid through Home Assistant's
`last_reported`. Readers without timestamps remain supported with freshness
`unknown`; they are not described as verified fresh.

Invalid or stale forecasts contribute zero solar energy through the existing
conservative fallback. Integration diagnostics expose freshness, source and
conversion. No stale numeric value is treated as evidence of future production.

## Thermal telemetry

Non-finite temperatures are missing readings. If a valid reading previously
reduced power, its cap is retained for up to five minutes during a sensor gap,
never above a newer incoming limit. After expiry the optional software derate
returns the incoming limit; hardware BMS protections remain authoritative.
Diagnostics distinguish valid, held and unavailable readings and report the held
charge cap. Charge and discharge hold histories are separate.

## Dashboard writes

Battery and system controls share one command path. A pending command disables
its control and suppresses duplicate writes to the same entity. The status banner
announces acceptance or failure; errors clear optimistic slider state and restore
the latest Home Assistant value. Acceptance means the service completed, not that
the battery has reached the requested power. Verify response in live telemetry.

## Accessible control evidence

Switches expose their checked state to assistive technology; switches, selects
and ranges have accessible names. Control help supports Enter/Space and Escape.
Battery cards show the live control owner, last commanded power, configured
ceilings, blocking reasons and known release times. Unknown commands or release
times remain unknown. These values describe control evidence, not proof that a
physical battery followed the command.
