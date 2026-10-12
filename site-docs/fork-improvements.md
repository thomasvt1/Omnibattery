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

## Power quantization

Allocation floors each share to 5 W, then assigns affordable increments by largest
remainder. Individual ceilings and the aggregate request are enforced after
rounding. A small unallocatable remainder is left unused rather than exceeding a
limit. The existing phase-protection pass can further reduce this allocation.

## Battery energy models

Driver capabilities now carry explicit directional efficiencies and charge/discharge activation crossovers. Existing drivers retain documented assumptions (0.85 each direction, 1750 W charge and 1500 W discharge crossovers); these are not claims of measured performance. Round-trip efficiency is the product of the two directions, and the user arbitrage cost setting remains independent.

Charge completion estimates and allocation weights account for AC-to-DC losses. Chronological charging uses the lowest eligible charge efficiency so switching between batteries cannot overstate stored energy. Export planning uses discharge efficiency, never the round-trip cost knob. Diagnostics expose the selected model and its provenance.

Drivers may optionally supply `EfficiencyMeasurement` records under `efficiency_measurements["charge"|"discharge"]`: paired energy over the same isolated converter, at least 30 samples, 300 seconds and 0.05 kWh input, with a finite ratio from 0.5 to 1 and an aware observation timestamp no older than one day. PV-contaminated, stale or invalid measurements leave the driver's defaults in place. Current drivers do not claim measurements they cannot independently observe.

The charging model is also used when calculating legacy fallback durations, charge-delay completion time, dashboard fallback quotas and quota carry-over. An already-started replacement slot is credited only for its remaining elapsed duration. Model reads inspect non-responsive exclusions without resetting retry state, using battery identity rather than display names.

Solar reserve and absorption calculations keep forecast demand on the AC side
and convert claims into required stored energy using the participating fleet’s
discharge efficiency. Live SOC targets recompute that conversion; 3 kWh of AC
demand requires 5 kWh stored at 60% discharge efficiency. Directional loss
assumptions are separate from configured round-trip price-arbitrage costs.

Predictive scalar deficits and chronological deadlines also account for
discharge losses. Simultaneous solar serves household load directly; only the
net surplus crosses the charge converter and only net demand crosses the
discharge converter. Plans retain the original AC intervals for dashboard
simulation separately from stored-energy intervals used for scheduling.

Charge-delay balances convert stored capacity to deliverable AC energy and net
solar production to stored energy, including unlock-time projections. Scalar
charge-delay totals use separated-flow losses because morning load and afternoon
PV cannot be assumed to coincide; dated chronological intervals can net flows. Curtailment
slot quotas remain AC output while SOC targets describe stored depletion.
For mixed fleets, headroom planning uses the highest participating discharge
efficiency: this is the conservative bound on stored depletion for a given AC
output, whereas demand reserves use the lowest efficiency.
