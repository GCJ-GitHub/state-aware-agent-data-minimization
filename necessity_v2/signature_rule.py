"""Compile one rebooking requirement and keep its verified receipt scoped."""
from copy import deepcopy
from dataclasses import replace

from .core import Action, Denied
from scripts.run_logistics_dependency import StationContractVerifier, StationRouteTable

SIGNATURE_STEP = 'signature_check'
SIGNATURE_ARTIFACT = 'signature_verified'
SIGNED_SUFFIX = '_signed'


def migrate_contracts(actions, rule):
    shared = rule['shared']
    condition = shared['condition']
    step = shared['step']
    verification = Action(step['id'], step['tool'], step['produces'], tuple(step['requires']),
                          tuple(step['fields']), (('assessment_ready', True), (condition, True)))
    affected = set(rule['contract']['apply_to_tools'])
    migrated = []
    for action in actions:
        if action.tool not in affected:
            migrated.append(action)
            continue
        migrated.append(replace(action, guards=action.guards + ((condition, False),)))
        migrated.append(replace(action, id=action.id + SIGNED_SUFFIX,
                                requires=action.requires + (verification.produces,),
                                guards=action.guards + ((condition, True),)))
    return migrated + [verification]


def migrate_routes(routes, fragments, rule):
    shared = rule['shared']
    condition = shared['condition']
    step = shared['step']
    fragments = deepcopy(fragments)
    fragments[step['id']] = {
        'step': step['id'], 'fields': step['fields'], 'include': ['identity'],
        'when': {'assessment_ready': True, condition: True},
    }
    affected_fragment = rule['route_table']['apply_to_fragment']
    migrated = []
    for route in routes:
        if affected_fragment not in route.get('include', ()):
            migrated.append(route)
            continue
        migrated.append({**route, 'when': {**route.get('when', {}), condition: False}})
        migrated.append({**route, 'step': route['step'] + SIGNED_SUFFIX,
                         'include': [*route['include'], step['id']]})
    return migrated, fragments


class SignatureReceiptReuse:
    """A shared recovery rule. A slot change alone does not invalidate the receipt."""

    signature_receipt = None

    def signature_stamp(self):
        action = self.registry.actions[SIGNATURE_STEP]
        fields = (*action.fields, 'parcel.station_ref')
        return (self.authority.resource, 'rebook_high_value_at_station', self.policy,
                self.identity_stamp(),
                tuple((field, self.authority.value_version(field)) for field in fields),
                tuple((name, self.authority.fact_version(name)) for name, _ in action.guards))

    def propose(self, nodes):
        sid = super().propose(nodes)
        session = self.sessions[sid]
        if (SIGNATURE_STEP in session['plan'].nodes
                and 'identity_verified' in session['artifacts']
                and self.signature_receipt == self.signature_stamp()):
            session['done'].add(SIGNATURE_STEP)
            session['artifacts'].add(SIGNATURE_ARTIFACT)
        return sid

    def _enabled(self, session, node):
        action = super()._enabled(session, node)
        if SIGNATURE_ARTIFACT in action.requires and self.signature_receipt != self.signature_stamp():
            raise Denied('Signature authorization verification is stale.')
        return action

    def execute(self, sid, node, values):
        result = super().execute(sid, node, values)
        if node == SIGNATURE_STEP:
            self.signature_receipt = self.signature_stamp()
        return result


class SignedContractVerifier(SignatureReceiptReuse, StationContractVerifier):
    pass


class SignedRouteTable(SignatureReceiptReuse, StationRouteTable):
    pass
