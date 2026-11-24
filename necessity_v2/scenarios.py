"""Reusable primitive contracts plus case state, not per-order allowed-field tables."""
from .core import Action, Authority, Policy, Registry, Verifier


def refund(wallet=True, bank=True, high=False, private_wallet_check=False,
           prefer_bank=False, privacy_first=True, exact_quotes=False, resource='refund-demo'):
    actions = [
        Action('wallet', 'wallet_refund', 'refund_done', fields=('order.wallet_ref',),
               guards=(('wallet_available', True), ('wallet_eligible', True))),
        Action('bank_verify_low', 'verify_bank', 'bank_verified',
               fields=('order.account_ref', 'customer.owner_ref'), guards=(('high_value', False),)),
        Action('bank_verify_high', 'verify_bank', 'bank_verified', requires=('identity_verified',),
               fields=('order.account_ref', 'customer.owner_ref'), guards=(('high_value', True),)),
        Action('identity', 'verify_identity', 'identity_verified', fields=('customer.identity_ref',)),
        Action('bank', 'bank_refund', 'refund_done', requires=('bank_verified',),
               fields=('order.account_ref',), guards=(('bank_available', True),)),
        Action('quotes', 'report_exact_quotes', 'quotes_reported',
               fields=('private.wallet_fee', 'private.bank_fee')),
    ]
    values = {'order.wallet_ref': 'SYN-WALLET', 'order.account_ref': 'SYN-ACCOUNT',
              'customer.owner_ref': 'SYN-OWNER', 'customer.identity_ref': 'SYN-IDENTITY',
              'private.wallet_fee': 2, 'private.bank_fee': 4, 'private.wallet_days': 1}
    facts = {'wallet_available': wallet, 'bank_available': bank, 'high_value': high,
             'backend_help_banner_visible': True}
    public = list(facts)
    probes = {}
    if private_wallet_check:
        # The user-approved question is fixed at fee<=3 and days<=2; the model
        # cannot submit arbitrary thresholds to reconstruct the raw values.
        probes['check_wallet_constraints'] = ('wallet_eligible', ('private.wallet_fee', 'private.wallet_days'),
            lambda v: v['private.wallet_fee'] <= 3 and v['private.wallet_days'] <= 2)
    else:
        facts['wallet_eligible'] = True
        public.append('wallet_eligible')
    authority = Authority(resource, values, facts, public, probes)
    ranks = (('wallet_refund', 1), ('bank_refund', 0)) if prefer_bank else ()
    policy = Policy(frozenset(a.tool for a in actions), frozenset(values),
                    utility_ranks=ranks, minimize_disclosure=privacy_first)
    goals = ('refund_done', 'quotes_reported') if exact_quotes else ('refund_done',)
    verifier = Verifier(authority, Registry(actions), policy, goals)
    for fact in public:
        verifier.accept_evidence(authority.public_receipt(fact))
    return verifier


def delivery(pickup=True, within_radius=True, redirect=True, resource='delivery-demo'):
    actions = [
        Action('pickup', 'arrange_pickup', 'delivery_done', fields=('parcel.postal_ref',),
               guards=(('pickup_available', True), ('pickup_within_radius', True))),
        Action('redirect', 'redirect_parcel', 'delivery_done',
               fields=('parcel.address_ref', 'parcel.contact_ref'), guards=(('redirect_available', True),)),
    ]
    values = {'parcel.postal_ref': 'SYN-POSTAL', 'parcel.address_ref': 'SYN-ADDRESS',
              'parcel.contact_ref': 'SYN-CONTACT', 'private.pickup_distance': 2 if within_radius else 9}
    authority = Authority(resource, values,
        {'pickup_available': pickup, 'redirect_available': redirect},
        public_facts=('pickup_available', 'redirect_available'),
        probes={'check_pickup_radius': ('pickup_within_radius', ('private.pickup_distance',),
                                       lambda v: v['private.pickup_distance'] <= 5)})
    policy = Policy(frozenset(a.tool for a in actions), frozenset(values))
    verifier = Verifier(authority, Registry(actions), policy, ('delivery_done',))
    for fact in authority.public:
        verifier.accept_evidence(authority.public_receipt(fact))
    return verifier


def appointments(resource='appointment-demo', online=True):
    # A shared identity dependency is expanded once even for two distinct goals.
    actions = [Action('identity', 'verify_identity', 'identity_verified', fields=('customer.identity_ref',))]
    values = {'customer.identity_ref': 'SYN-SHARED-IDENTITY'}
    facts = {}
    for unit in ('session1', 'session2'):
        values[unit + '.member_ref'] = 'SYN-' + unit.upper()
        values[unit + '.address_ref'] = 'SYN-ADDRESS-' + unit.upper()
        facts[unit + '.online_available'] = online
        facts[unit + '.home_available'] = True
        actions += [
            Action(unit + '.online', 'book_online', unit + '.done', requires=('identity_verified',),
                   fields=(unit + '.member_ref',), guards=((unit + '.online_available', True),)),
            Action(unit + '.home', 'book_home', unit + '.done', requires=('identity_verified',),
                   fields=(unit + '.member_ref', unit + '.address_ref'), guards=((unit + '.home_available', True),)),
        ]
    authority = Authority(resource, values, facts, public_facts=tuple(facts))
    policy = Policy(frozenset(a.tool for a in actions), frozenset(values))
    verifier = Verifier(authority, Registry(actions), policy, ('session1.done', 'session2.done'))
    for fact in facts:
        verifier.accept_evidence(authority.public_receipt(fact))
    return verifier


def scripted_complete(verifier, plan):
    """A mechanics-only driver. It is NOT an LLM or autonomous-agent result."""
    sid = verifier.propose(plan.nodes)
    actual_values = {}
    done = set()
    while done != set(plan.nodes):
        session = verifier.sessions[sid]
        ready = sorted(n for n in plan.nodes - done
                       if set(verifier.registry.actions[n].requires) <= session['artifacts'])
        if not ready:
            raise AssertionError('No enabled action in an accepted acyclic plan.')
        node = ready[0]
        grant = verifier.issue(sid, node)
        actual_values.update(verifier.read(grant['grant'], grant['fields'], verifier.authority.resource))
        fields = verifier.registry.actions[node].fields
        result = verifier.execute(sid, node, {f: actual_values[f] for f in fields})
        done.add(node)
    assert result['complete']
    return {'mode': 'scripted_mechanics_only', 'model_calls': 0,
            'selected_actions': sorted(plan.nodes), 'derived_field_union': sorted(plan.fields),
            'disclosed_raw_fields': sorted(verifier.disclosed),
            'monitor_metrics': dict(verifier.metrics), 'connector_metrics': dict(verifier.authority.metrics),
            'events': list(verifier.events)}


def two_private_checks(fee_ok=True, speed_ok=True, resource='query-order-demo'):
    """Two independent provider checks; a more revealing bank path is a fallback.

    Only two separate checks are registered. All comparison arms must get the
    same adapters; introducing an aggregate API to one arm would be a confound.
    """
    actions = [
        Action('wallet', 'wallet_refund', 'refund_done', fields=('order.wallet_ref',),
               guards=(('wallet_fee_ok', True), ('wallet_speed_ok', True))),
        Action('bank', 'bank_refund', 'refund_done', fields=('order.account_ref', 'customer.owner_ref')),
    ]
    values = {'order.wallet_ref': 'SYN-WALLET', 'order.account_ref': 'SYN-ACCOUNT',
              'customer.owner_ref': 'SYN-OWNER', 'private.fee': 1 if fee_ok else 9,
              'private.days': 1 if speed_ok else 9}
    probes = {
        'check_fee': ('wallet_fee_ok', ('private.fee',), lambda v: v['private.fee'] <= 3),
        'check_speed': ('wallet_speed_ok', ('private.days',), lambda v: v['private.days'] <= 2)}
    authority = Authority(resource, values, {}, probes=probes)
    policy = Policy(frozenset(a.tool for a in actions), frozenset(values))
    return Verifier(authority, Registry(actions), policy, ('refund_done',))
