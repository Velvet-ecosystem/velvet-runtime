# Local Intent Gateway

The local intent gateway is the only client-facing request seam for the Runtime pipeline.

Clients submit only:

- a normalized intent ID
- a published route ID
- route-bounded parameters

Clients cannot supply:

- executor names
- profile, session, body, or surface identity
- capabilities or targets
- module paths
- shell commands
- Python callables
- hardware handles

A trusted local route binds the public route ID to one action, capability, target, approved executor name, and explicit parameter-name allowlist.

The gateway fills identity fields from the already verified boot context and passes the resulting strict intent into `RuntimePipeline`.

Unknown routes, extra request fields, non-normalized identifiers, and parameters outside the route allowlist are rejected before Court authorization.

This patch defines the gateway contract only. It does not expose a network listener, register any real route at boot, or make hardware available.
