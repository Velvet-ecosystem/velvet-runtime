"""
velvet-runtime: services/safe_publish.py
==========================================
Hardened safe_publish callable for use across the Velvet runtime.

SECURITY MODEL:
  _SafePublish is a callable class (not a function closure) that wraps
  enforcer.publish. It provides structural hardening against the most
  common Python-level bypass attempts:

  BLOCKED:
    - .bus, .enforcer, .publish attribute access  (no __dict__, __slots__ only)
    - Monkeypatching via setattr                  (__setattr__ raises)
    - __closure__ traversal                       (not a function; no __closure__)
    - vars()                                      (no __dict__)
    - Direct name guessing (.bus, ._fn, .__fn)    (all blocked by __slots__)

  KNOWN LIMITATION — this class does NOT contain malicious in-process code:
    _SafePublish blocks casual and accidental leaks. It is interface hygiene,
    not a security sandbox.

    A malicious in-process plugin can still do the following:

      fn = object.__getattribute__(publish, '_SafePublish__fn')
      enforcer = fn.__self__
      bus = enforcer.bus          # depending on enforcer implementation
      bus._publish(...)           # direct bus access, bypassing enforcement

    This multi-hop path requires deliberate CPython introspection knowledge.
    It cannot be blocked in pure Python without process isolation or a
    C-extension-level slot implementation.

    Consequences:
    - The "enforcement still applies" claim is FALSE for this path.
      An attacker who reaches bus._publish directly bypasses the enforcer
      and receipt validation entirely.
    - _SafePublish stops accidental misuse and raises the bar against
      naive or opportunistic bypass attempts. It does not stop a determined
      attacker operating in the same process.

    Correct mitigation: modules are trusted plugins reviewed before
    deployment. Untrusted module execution requires process isolation
    (subprocess, container, or IPC boundary). This is a future phase.

USAGE:
    from services.safe_publish import make_safe_publish
    sp = make_safe_publish(enforcer)
    sp(event_type="TEST_PING", payload={"x": 1})
"""


class _SafePublish:
    """
    Immutable callable wrapping enforcer.publish.

    __slots__ eliminates __dict__ and prevents attribute injection.
    __setattr__ override prevents monkeypatching.
    Not a function — has no __closure__, no __code__, no __globals__.
    """

    __slots__ = ('__fn',)

    def __init__(self, enforcer_publish_fn: callable):
        # Store via name mangling: accessible as _SafePublish__fn
        # Not accessible as .bus, .enforcer, ._fn, .__fn
        object.__setattr__(self, '_SafePublish__fn', enforcer_publish_fn)

    def __call__(
        self,
        event_type: str,
        payload: dict,
        receipt_id: str = None,
    ) -> None:
        self.__fn(  # noqa: SLF001
            event_type=event_type,
            payload=payload,
            receipt_id=receipt_id,
        )

    def __setattr__(self, name, value):
        raise AttributeError(
            "safe_publish is immutable. "
            "Attempted attribute assignment is not permitted."
        )

    def __repr__(self):
        return "<safe_publish: enforcer-gated event publish interface>"


def make_safe_publish(enforcer) -> _SafePublish:
    """
    Build and return a hardened safe_publish callable.

    Args:
        enforcer: EventEnforcer instance. Stored internally as a bound
                  method reference — NOT accessible as a named attribute.

    Returns:
        _SafePublish instance. Call as:
            safe_publish(event_type, payload, receipt_id=None)
    """
    return _SafePublish(enforcer.publish)
