"""Real admission boundary: publisher assertions never substitute for proof."""
from services.body_capacity import LinuxResourceProbe, NodeResourceAdvertisement, NodeResourceRegistry
from services.body_resource_transport import (_node_resource_advertisement_to_dict,
    _node_resource_advertisement_from_dict)
from services.headless_node_supervisor import HeadlessNodeConfig, HeadlessNodeSupervisor

BOOT = '00000000-0000-4000-8000-000000000001'

def advertisement(**changes):
    values = dict(node_id='lyra', body_id='body', observed_at=100.0, resources=(),
                  body_verified=True, continuity_verified=True, boot_id=BOOT)
    values.update(changes)
    return NodeResourceAdvertisement(**values)


def test_self_report_and_wire_round_trip_cannot_admit_node():
    registry = NodeResourceRegistry(body_id='body', clock=lambda: 100.0)
    item = _node_resource_advertisement_from_dict(_node_resource_advertisement_to_dict(advertisement()))
    assert not registry.register(item).accepted
    assert registry.capacity_snapshot().node_ids == ()


def test_proof_revocation_and_expiry_remove_previously_eligible_node():
    now = [100.0]
    proof = [True]
    registry = NodeResourceRegistry(body_id='body', clock=lambda: now[0],
        verification_provider=lambda item: proof[0])
    assert registry.register(advertisement()).accepted
    proof[0] = False
    assert registry.get('lyra') is None
    proof[0] = True
    assert registry.register(advertisement()).accepted
    now[0] = 120.0
    assert registry.snapshot() == ()


def test_missing_malformed_boot_and_stale_future_nonfinite_times_fail_closed():
    registry = NodeResourceRegistry(body_id='body', clock=lambda: 100.0,
        verification_provider=lambda item: True)
    for changes in ({'boot_id': ''}, {'boot_id': 'bad'}, {'body_id': 'other'},
                    {'observed_at': 80.0}, {'observed_at': 101.0}):
        assert not registry.register(advertisement(**changes)).accepted
    for value in (float('inf'), float('nan')):
        try:
            advertisement(observed_at=value)
        except ValueError:
            pass
        else:
            raise AssertionError('nonfinite timestamp admitted')


def test_provider_exception_is_denial_and_removes_current_eligibility():
    def failed(item):
        raise RuntimeError('proof source offline')
    registry = NodeResourceRegistry(body_id='body', clock=lambda: 100.0,
        verification_provider=failed)
    assert not registry.register(advertisement()).accepted


def test_configuration_assertions_do_not_become_verified_status(tmp_path):
    config = HeadlessNodeConfig('lyra', 'body', 'velour', tmp_path/'status.json',
                              body_verified=True, continuity_verified=True)
    result = HeadlessNodeSupervisor(config).observe_once(now=100.0)
    assert not result['body_verified'] and not result['continuity_verified']
    assert result['verification']['configured_body_assertion'] is True
    assert result['verification']['state'] == 'unverified'
    probe = LinuxResourceProbe(node_id='lyra', body_id='body',
                               body_verified=True, continuity_verified=True)
    item = probe.probe(now=100.0)
    assert not item.body_verified and not item.continuity_verified


def test_independent_proof_binding_rejects_replayed_previous_boot():
    current_boot = ['00000000-0000-4000-8000-000000000002']
    registry = NodeResourceRegistry(body_id='body', clock=lambda: 100.0,
        verification_provider=lambda item: item.boot_id == current_boot[0])
    assert not registry.register(advertisement()).accepted
    assert registry.register(advertisement(boot_id=current_boot[0])).accepted
    current_boot[0] = BOOT
    assert registry.get('lyra') is None
