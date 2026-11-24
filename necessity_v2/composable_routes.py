"""A refreshed field-table baseline that composes independently authored goal recipes."""
from itertools import product

from .core import Plan, Registry, Verifier
from .route_baseline import RefreshedRouteTable, ReusableIdentityVerifier, RouteRow


class RecipeRegistry(Registry):
    def __init__(self, actions, rows):
        super().__init__(actions)
        self.rows = tuple(rows)

    def compose(self, goals):
        choices = [[row for row in self.rows if row.goals == {goal}] for goal in goals]
        result = []
        for rows in product(*choices):
            fields_by_step = {}
            for row in rows:
                for node, fields in row.steps:
                    if node in fields_by_step and fields_by_step[node] != fields:
                        raise ValueError('Conflicting table fields for a shared step.')
                    fields_by_step[node] = fields
            if len({self.actions[n].produces for n in fields_by_step}) != len(fields_by_step):
                continue
            guards = frozenset(condition for row in rows for condition in row.conditions)
            if any((name, not expected) in guards for name, expected in guards):
                continue
            plan = Plan(frozenset(fields_by_step), frozenset(row.root for row in rows),
                        frozenset(field for fields in fields_by_step.values() for field in fields),
                        guards)
            result.append((plan, fields_by_step))
        return sorted(result, key=lambda pair: pair[0].id)

    def plans(self, goals):
        return [plan for plan, _ in self.compose(goals)]


class LogisticsIdentityVerifier(ReusableIdentityVerifier):
    def identity_stamp(self):
        resource, _, *versions = super().identity_stamp()
        return resource, 'logistics_identity', *versions


class ComposableRouteTable(RefreshedRouteTable, LogisticsIdentityVerifier):
    """Refresh and table-gated reads with goal composition and shared prerequisites."""
    def __init__(self, authority, actions, policy, goals, rows):
        recipes = RecipeRegistry(actions, rows)
        super().__init__(authority, recipes, policy, goals, ())
        self.rows = {plan.nodes: RouteRow(frozenset(goals), min(plan.roots),
                                        tuple(fields.items()), tuple(sorted(plan.guards)))
                     for plan, fields in recipes.compose(goals)}

    def frontier(self):
        # Share ranking and trusted-evidence rules, while enumerating table recipes.
        return Verifier.frontier(self)
