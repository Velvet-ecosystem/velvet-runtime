# Environmental Sensors Module Package

This is the first recovered archive module rebuilt for `velvet.module_package.v1`.

It does not open I2C, GPIO, serial, network, shell, voice, or control surfaces. Runtime must provide a reviewed local service named:

```text
environment-reader-service
```

That service exposes:

```python
read_environment() -> mapping
```

Accepted fields:

- `cabin_temperature_c`
- optional `outside_temperature_c`
- `ambient_light_lux`
- optional `relative_humidity_percent`
- optional `confidence`
- optional `calibration_version`

The package publishes `environmental_conditions` as read-only body evidence. It retains only a bounded sample counter, last accepted sample, and last error for hot-swap handoff.
