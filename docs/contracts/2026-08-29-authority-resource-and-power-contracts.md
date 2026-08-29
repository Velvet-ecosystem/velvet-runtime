# Authority, resource, and power contracts

Date: 2026-08-29
Status: contract draft
Owner repo: velvet-runtime

## Purpose

Runtime owns the place where Velvet's intentions meet capability, resource limits, power reality, and physical authority. These contracts turn newer briefing ideas into runtime boundaries before any live implementation touches hardware.

## 1. Dispatch-Time Authority Contract

Authority must be checked at the last possible safe moment before physical dispatch.

Canonical chain:

```text
intent approved -> capability resolved -> physical target verified -> authority still current -> dispatch -> receipt
```

Required checks:

- caller still has authority
- target still exists
- target health still permits action
- vehicle or body state still allows action
- simulation/physical target has not changed
- required owner presence still valid
- safety gate not newly active
- receipt backend available or safe fallback declared

Refusal reasons:

```text
authority_missing
capability_unavailable
capability_degraded
owner_presence_required
simulated_target_only
physical_target_locked
safety_gate_active
stale_sensor_data
dependency_unhealthy
court_denied
vehicle_state_disallows
maintenance_mode_required
receipt_backend_unavailable
manual_override_required
```

Rule: approval earlier in the chain never guarantees dispatch later.

## 2. Physical Capability Descriptor

A physical organ must describe what it can measure, change, tolerate, and refuse.

Suggested shape:

```yaml
capability_name: string
owner: string
physical_target: string
measures: [string]
changes: [string]
read_primitives: [string]
write_primitives: [string]
safe_ranges: map
unsafe_ranges: map
latency_class: reflex | bounded | best_effort
authority_required: read | propose | command | emergency
simulated_available: boolean
refusal_reasons: [string]
receipt_type: string
```

Rule: discoverability never implies authority. A model, module, or UI may learn that hardware exists without gaining permission to operate it.

## 3. Retry Budget Contract

Reconnect storms and synchronized panic are runtime failures.

Suggested fields:

```yaml
service_id: string
max_retries_per_window: integer
window_ms: integer
backoff_strategy: exponential | fixed | none
jitter_required: boolean
global_retry_ceiling: integer
degraded_after_failures: integer
offline_after_failures: integer
shared_dependency_id: string | null
receipt_on_budget_exhausted: boolean
```

Rules:

- no handmaiden may retry indefinitely
- shared dependencies need a global retry ceiling
- jitter is preferred so organs do not stampede together
- exhausted retry budget emits health and receipt events

## 4. Mixed-Criticality Resource Contract

Runtime should admit work only if the body can afford the whole footprint.

Resource dimensions:

```text
compute + RAM + watts + transient headroom + cooling + network bandwidth + storage writes
```

Service classes:

```text
Class 0: emergency and safety critical
Class 1: identity, Court, receipts, health
Class 2: vehicle state and diagnostics
Class 3: owner interaction and UI
Class 4: comfort and convenience
Class 5: archive, indexing, experiments, entertainment
```

Rules:

- Class 0 and Class 1 receive protected resources first.
- Degraded mode sheds from highest class number downward.
- A task can be refused even when CPU is technically free.
- Receipts record service shedding and resource refusal.

## 5. Protected Reserve / Borrowable Resource Model

An idle protected reserve is not automatically free.

Suggested fields:

```yaml
total_resource: number
protected_reserve: number
temporarily_borrowable: number
reclaim_latency_ms: integer
borrower_class_limit: integer
forced_reclaim_allowed: boolean
receipt_on_reclaim: boolean
```

Applies to:

- electrical watts
- RAM
- SSD bandwidth
- network queues
- CPU cores
- GPU/NPU time
- storage space

## 6. Power-Loss Transaction Contract

When supply collapses, every node should shut down with bounded truth.

Required behavior:

```text
power_loss_detected -> stop noncritical work -> flush receipts/state -> mark unfinished operations -> unmount writable storage -> report shutdown result
```

Suggested fields:

```yaml
node_id: string
reserve_window_ms: integer | null
power_loss_detected_at: string
noncritical_work_stopped: boolean
receipts_flushed: boolean
state_flushed: boolean
unfinished_operations_marked: [string]
storage_unmounted_cleanly: boolean
shutdown_completed_before_reserve_expired: boolean
recovery_required: boolean
receipt_id: string
```

## 7. Thermal-Aftermath Contract

Heat persists after work stops. Scheduler decisions should include thermal momentum.

Suggested fields:

```yaml
heat_source: string
recent_workload_history: string
current_temperature_c: number
thermal_trajectory: rising | stable | falling | unknown
cooling_state: off | passive | fan | pump | hvac | unknown
predicted_cooldown_ms: integer | null
low_priority_work_blocked_until: string | null
thermal_sink: cabin | exterior_air | chassis | coolant_loop | enclosure | unknown
cooling_power_cost_w: number | null
```

## 8. Power Supervisor Contract

Power hardware is not a dumb brick.

Required fields:

```yaml
supervised_node: string
supervisor_node: string
rails: [string]
wake_sources: [string]
brownout_thresholds: map
keep_alive_memory: boolean
watchdog_owner: string
can_wake_supported: boolean
power_cycle_authority: string
max_recovery_attempts: integer
cooldown_period_ms: integer
safe_fallback_if_linux_missing: string
receipt_type: string
```

## 9. Power Path Measurement Contract

Bench builds should measure where electricity actually goes.

Canonical path:

```text
source voltage -> protection drop -> converter efficiency -> branch current -> transient peak -> module voltage -> heat
```

Suggested measurements:

- boot peak
- idle draw
- active draw
- inference startup transient
- amplifier or actuator wake transient
- shutdown leakage
- regulator droop
- recovery time
- neighboring-node disturbance

## 10. Compute Headroom Contract

Protected duties reserve CPU, RAM, electrical, and thermal headroom before AI workloads are admitted.

Suggested fields:

```yaml
node_id: string
protected_cpu_percent: number
protected_ram_mb: integer
protected_watts: number
protected_thermal_margin_c: number
optional_ai_allowed: boolean
admission_reason: string
refusal_reason: string | null
```

## 11. Failure-Domain Contract

Redundancy must identify shared dependencies.

Suggested fields:

```yaml
primary_path: string
backup_path: string
shared_fuse: string | null
shared_regulator: string | null
shared_switch: string | null
shared_storage: string | null
shared_network_switch: string | null
shared_cooling: string | null
shared_clock: string | null
shared_configuration_source: string | null
shared_wiring_route: string | null
failure_domain_id: string
```

Rule: two computers attached to one failing dependency are not independent redundancy.

## Non-goals

- No physical command implementation in this document.
- No actuator enablement.
- No bypass of Court.
- No assumption that a future AI model may dispatch hardware directly.
