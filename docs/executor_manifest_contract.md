# Executor Manifest Contract

Every executor must declare its interface before trusted Runtime wiring may register it.

A manifest contains its schema version, normalized name, version, capability, targets, named safety gate, read-only flag, and parameter specifications.

Supported parameter types are boolean, integer, number, and string.

Parameters may declare whether they are required, numeric minimum and maximum values, a unit label, and allowed choices.

Runtime rejects unknown parameters, missing required parameters, incorrect types, values outside declared bounds or choices, duplicate parameter names, unnamed safety gates, and unsupported schemas.

The manifest contains metadata only. It does not load code or grant authority. Handler code remains locally reviewed and still requires Court authorization, a matching safety gate, replay protection, and receipts.

This contract adds parsing and parameter validation only. It registers no executors, routes, or hardware authority.
