# Emergency-First Action Eligibility

When a real emergency is active, Velvet must not make life-safety work wait behind ordinary vehicle, comfort, media, or convenience work.

Emergency eligibility therefore has a **life-safety priority band** that is evaluated before ordinary work when any of these trusted incident states is active and verified:

- confirmed emergency;
- accident/collision incident;
- manually started emergency protocol.

A manual emergency start is first-priority once the trusted incident boundary has accepted it. Runtime does not accept an untrusted payload merely claiming that emergency mode was started.

## Priority rule

```text
verified active emergency context
  -> life-safety priority rank 0
  -> preempt ordinary work
  -> expedited incident-action policy evaluation
  -> strict Court intent only if separately eligible
  -> Court / capability / safety / approved executor
  -> measured outcome
```

The purpose of the expedited path is to remove avoidable software delay, not governance.

Emergency-first eligibility means **consider this first**. It does not mean **automatically approve this**.

## What remains mandatory

Emergency priority does not bypass:

- incident identity binding;
- requester/proposal provenance;
- Court authorization;
- capability scope;
- safety gates and interlocks;
- approved executor selection;
- replay/duplicate protections;
- receipt persistence required for the consequential path;
- measured execution feedback.

If a safety interlock is itself necessary to prevent greater harm, it remains authoritative over unsafe execution. Emergency priority outranks ordinary work, not physics.

## Manual activation

A deliberately started emergency protocol is treated as a life-safety incident immediately after its trusted activation boundary verifies the start.

This supports cases where a human can see the emergency before Velvet's sensors have enough evidence, or where a crash/medical event requires immediate escalation.

The Runtime eligibility layer receives only the already-verified activation state. It does not decide whether a random remote caller, network packet, or responder voice is allowed to start emergency mode.

## Design laws

**In an active emergency, life-safety work goes first.**

**Emergency priority shortens the path to a decision. It does not remove the gates that make the decision safe.**

**Manual emergency activation is first-priority once verified, not once merely claimed.**
