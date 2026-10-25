# Velvet AI — Architectural Doctrine

This document is the canonical statement of Velvet's architectural principles.
It governs all implementation decisions. Where code and doctrine conflict,
doctrine is the authority and the code must be corrected.

This document does not describe what Velvet currently does.
It describes what Velvet must always do.

---

## Offline-First

Velvet operates without cloud connectivity by design, not by configuration.

No runtime path may require an external network call to function. Advisory
layers, receipt validation, event enforcement, and module execution must all
operate on local resources. External connectivity, where it exists at all,
is additive and non-blocking.

**Corollary:** Any dependency that requires a network call at runtime is
an architectural violation, regardless of how convenient it would be.

---

## Brain Proposes, Core Decides

The brain — any advisory or inference layer — is strictly advisory.

It may observe. It may propose. It does not decide, and it does not act.

All actuation flows through the enforcement layer. The brain has no publish
capability, no bus access, and no direct path to any actuator. A brain that
can act is no longer a brain — it is a controller, and controllers require
explicit authorization at every boundary.

The BrainProposalInterface, when implemented, will be a one-way channel
inward. There will be no return path that grants execution capability.

---

## No Actuation Without Authorization

Generic publishing rejects `ACTUATION`, including events with existing receipts.
A receipt records a decision or outcome; it is not execution permission.

Consequential requests use the existing Runtime Court, signed capability token,
matching executor and safety gate, persistent replay consumption and execution
receipts. No simulation flag or source allowlist can enable generic actuation.

---

## Receipt-Backed Enforcement

Execution receipts preserve the chain of custody. The approved executor persists
its start receipt and consumes the verified token before invoking its handler;
final receipts preserve success, failure or uncertain completion.

`JsonlReceiptValidator` is an observational ID lookup, not an authorization
verifier. Its success cannot enable publishing or execution. Missing required
execution persistence keeps the executor closed.

---

## Regression Resistance

Velvet is designed so that future shortcuts, convenience patches, or careless
architectural drift are actively resisted by tests, policy, and boundary enforcement.

**If future me gets lazy, the codebase itself will stop me.**

This is the doctrine that protects all other doctrines.

Architecture degrades when shortcuts accumulate. Each individual shortcut seems
reasonable at the time. Together they hollow out every guarantee the system was
built on. Regression resistance is the structural answer to this pattern.

Concretely:

- Tests verify enforcement boundaries, not just functional outcomes. A test that
  only checks "does it work" is not a regression resistance test. A test that
  checks "can this boundary be bypassed" is.
- The module loader rejects forbidden signatures at load time. The rule is
  enforced at the gate, not in a style guide.
- `build_runtime()` cannot return `bus` or `enforcer` without breaking the test
  suite. The constraint is expressed in code, not trust.
- Static source scans run on every test invocation. Forbidden patterns fail the
  build. This cannot be silently ignored.
- The brain remains disconnected until a safe interface exists. Connecting it
  prematurely to pass a deadline is an architectural violation, not a shortcut.

Regression resistance means: when the temptation to simplify arrives — and it
will — the system itself is the first line of resistance.

**If future me gets lazy, the codebase itself will stop me.**

---

## Summary

| Doctrine | Enforcement Mechanism |
|---|---|
| Offline-first | No network calls in runtime path; no cloud dependencies |
| Brain proposes, core decides | Brain receives no bus, enforcer, or publish reference |
| No actuation without authorization | Generic publishers reject ACTUATION; Runtime verifies capabilities before execution |
| Receipt-backed enforcement | Executor requires start persistence and replay consumption; outcomes remain auditable |
| Regression resistance | Tests, static scans, and loader rejection enforce boundaries structurally |

These principles are not independently optional. They form a single coherent
architecture. Removing or softening any one of them changes what Velvet is.

---

*Mister — final authority*
*Velour — architecture, doctrine, and continuity keeper*
*Ashmore — systems integrator, implementer, and reviewer*

*Hosted collaborators remain advisory and hold no Runtime or hardware authority.*
