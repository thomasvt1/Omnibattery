# Omnibattery fork improvement roadmap

Target repository: **thomasvt1/Omnibattery**. Baseline: `ce03e675` (v1.5.0).

This roadmap is published before implementation. Work proceeds in the order below, one tested implementation PR at a time. Each PR targets this fork’s `main`, closes its tracking issue, and updates this document. No writes or PRs target the upstream repository.

## Delivery sequence

### 1. Preserve absolute time across DST in price planning

- Status: completed (implementation PR linked from the issue)
- Issue: [1](https://github.com/thomasvt1/Omnibattery/issues/1)
- Scope: Normalize provider price periods to UTC-aware instants, preserve compatibility at legacy wall-clock boundaries, validate period durations, and test spring/autumn transitions.
- Acceptance: One actual hour remains one hour across both DST transitions; repeated periods remain distinct; pricing regression tests pass.

### 2. Enforce solar forecast freshness and validity

- Status: completed (implementation PR linked from the issue)
- Issue: [2](https://github.com/thomasvt1/Omnibattery/issues/2)
- Scope: Add forecast freshness metadata, validate last report/issuance and forecast date, reject stale numeric forecasts with explicit fallback diagnostics, and preserve lightweight consumers.
- Acceptance: Old numeric forecasts cannot suppress grid charging; unchanged recently reported states remain valid; freshness and fallback reasons are observable and tested.

### 3. Handle invalid and missing thermal telemetry conservatively

- Status: completed (implementation PR linked from the issue)
- Issue: [3](https://github.com/thomasvt1/Omnibattery/issues/3)
- Scope: Reject non-finite thermal inputs, retain the last valid derated cap for a bounded interval, expose degraded telemetry status, and document the eventual fallback.
- Acceptance: NaN/Infinity never crash limiting; hot-to-missing transitions retain their cap temporarily; expiry and recovery are tested.

### 4. Report dashboard command progress and failures

- Status: completed (implementation PR linked from the issue)
- Issue: [4](https://github.com/thomasvt1/Omnibattery/issues/4)
- Scope: Route dashboard service writes through a shared pending/success/failure helper, suppress duplicates, restore actual values after errors, and distinguish service acceptance from physical delivery.
- Acceptance: Rejected writes display actionable feedback and clear optimistic slider state; pending commands cannot be duplicated; successful writes never claim physical delivery.

### 5. Improve control accessibility and battery decision explanations

- Status: completed (implementation PR linked from the issue)
- Issue: [5](https://github.com/thomasvt1/Omnibattery/issues/5)
- Scope: Associate accessible labels with switches/selects/ranges, expose switch state semantics, support keyboard help, and show current owner/request/limits/release evidence for each battery.
- Acceptance: Controls have accessible names and switch states; keyboard users can reach help; explanations use live evidence and show unknown release times honestly.

### 6. Preserve individual and fleet power caps after quantization

- Status: completed (implementation PR linked from the issue)
- Issue: [6](https://github.com/thomasvt1/Omnibattery/issues/6)
- Scope: Quantize allocations down at hard limits and distribute remaining 5 W increments only within per-device and aggregate budgets.
- Acceptance: 803 W never allocates 805 W; total allocation never exceeds a 1598 W budget; heterogeneous fleet and charging/discharging invariants are tested.

### 7. Model battery-specific efficiency and activation crossovers

- Status: completed (implementation PR linked from the issue)
- Issue: [7](https://github.com/thomasvt1/Omnibattery/issues/7)
- Scope: Introduce validated per-driver energy model defaults and optional measured efficiency evidence, separate charge/discharge/round-trip semantics, and consume battery-specific crossover thresholds in fleet selection.
- Acceptance: Mixed fleets can expose distinct energy models; invalid measurements fall back safely; planning uses directional efficiencies without confusing round-trip values; legacy defaults remain explicit.

### 8. Track forecast error and expose calibrated uncertainty

- Status: completed (implementation PR linked from the issue)
- Issue: [8](https://github.com/thomasvt1/Omnibattery/issues/8)
- Scope: Persist issued forecast snapshots and matched outcomes, calculate bias/error bands without hindsight leakage, expose calibration diagnostics, and apply bounded conservative uncertainty to planning when sufficient evidence exists.
- Acceptance: Unscored/missing observations never become zero outcomes; evaluation matches issuance horizon; small samples remain uncalibrated; reserve adjustments and forecast diagnostics are tested.

### 9. Adapt native Solcast and Forecast.Solar period curves

- Status: completed (implementation PR linked from the issue)
- Issue: [9](https://github.com/thomasvt1/Omnibattery/issues/9)
- Scope: Parse native provider period shapes with explicit power/energy units and durations, validate ordering/duplicates/overlaps, and expose provider versus fallback provenance.
- Acceptance: Representative native payloads produce correct kWh and DST-safe periods; malformed/overlapping data falls back explicitly; scalar budgets remain consistent.

### 10. Extract immutable control decision and execution contracts

- Status: planned
- Issue: [10](https://github.com/thomasvt1/Omnibattery/issues/10)
- Scope: Introduce pure immutable input/decision records for ownership, requested power, applied limits and reasons; extract final decision construction from the controller and retain one execution path.
- Acceptance: Final automatic writes consume a validated decision; ownership and caps are tested independently; diagnostics can report the same decision used for execution; existing controller behavior remains covered.

### 11. Add browser behavior tests and automatic HA test selection

- Status: planned
- Issue: [11](https://github.com/thomasvt1/Omnibattery/issues/11)
- Scope: Add a browser harness for real dashboard service failure, keyboard/mobile and unavailable-state behavior; select HA integration tests automatically rather than by a maintained file list; document reproducible checks.
- Acceptance: Browser tests execute rendering and interaction; unit and HA jobs select disjoint complete test sets; new hass-fixture tests enter the HA job automatically; CI runs the relevant checks.

## Validation and release discipline

- Run focused regressions for each change and check integration contracts when shared paths change.
- Run Python tests with Python 3.14 and the repository test dependencies; localhost fake battery tests require local networking.
- Add executable browser coverage for frontend interactions.
- Check the exact PR head and available CI results before merging; report any external workflow limitations.
- Keep documentation, fallbacks, and diagnostics consistent with the implemented behavior.
- Finish with the complete Python and browser suites, a clean checkout, and merged PR links.

## Review gate

Read every review summary, inline comment and PR conversation comment before merging. Wait for in-progress reviews to finish, fix actionable findings, and inspect the final head again. PRs #13–#17 received findings after their initial merges; a corrective PR addresses local-time consumers, forecast invalidation, stale thermal readings, concurrent command failures and explanation/accessibility gaps before item 7 resumes.
