"""
Structural regression test for the exact bug class found in this
audit: require_scoped_role() reads event_id from the URL PATH, so
applying it to a route whose path doesn't contain {event_id} makes
that endpoint permanently return 403 for every caller, including
Super Admin. This was found on five routes (registrations approve/
reject, notifications send, teams approve, tickets check-in) where the
router dependency was both broken AND redundant with a correct
in-service check.

This test walks every registered route and fails if any of them uses
require_scoped_role's distinctive "request: Request" dependency
signature without {event_id} in the route's own path — so this class
of bug can't be silently reintroduced in a sixth route later.
"""
import inspect

from fastapi import Request

from app.main import app


def _dependant_uses_scoped_role_pattern(dependant) -> bool:
    """require_scoped_role's inner _check() takes a `request: Request`
    parameter (needed to read path_params) — require_role's _check()
    does not. This is what distinguishes the two dependency factories
    without relying on their shared internal function name "_check"."""
    sig = inspect.signature(dependant.call)
    request_param = sig.parameters.get("request")
    return request_param is not None and request_param.annotation is Request


def test_every_scoped_role_dependency_route_has_event_id_in_its_path():
    offending_routes = []

    for route in app.routes:
        dependant = getattr(route, "dependant", None)
        if dependant is None:
            continue

        for dependency in dependant.dependencies:
            if _dependant_uses_scoped_role_pattern(dependency):
                if "{event_id}" not in route.path:
                    offending_routes.append((route.path, list(route.methods or [])))

    assert offending_routes == [], (
        "The following routes use require_scoped_role() but don't have "
        "{event_id} in their path — this dependency reads event_id from "
        "the URL path, so these routes will ALWAYS return 403 regardless "
        "of role. Either add {event_id} to the path, or move the "
        "permission check into the service layer (loading the entity "
        "first, then checking scope against its real event_id) instead:\n"
        f"{offending_routes}"
    )