from app.dispatch_engine.models import EngineDemand, EngineRoute


class StoreRouteConstraint:
    def is_satisfied(
        self,
        demand: EngineDemand,
        route: EngineRoute,
        store_route_ids: dict[int, set[int]],
    ) -> bool:
        return route.id in store_route_ids.get(demand.store_id, set())

