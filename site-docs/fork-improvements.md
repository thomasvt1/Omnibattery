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
