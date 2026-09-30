# Sensor LAN Ingress v0.1 design notes

This pass intentionally stops at authenticated admission and does not open a network listener.

Reasons:

- Runtime's in-process EventBus remains private to Runtime.
- Network transport can change without changing the normalized sensor contract.
- A listener can be reviewed separately for binding address, TLS/WireGuard/Tailscale policy, backpressure, rate limiting, and service supervision.
- HMAC node identity and replay handling can be tested deterministically without a live network.

The next LAN-specific change should bind one deployment transport to `SensorLanIngress`, then pass only verified admissions into Runtime's normal enforcement/publish path.
