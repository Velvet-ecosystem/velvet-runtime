# SPDX-License-Identifier: GPL-3.0-only
"""Narrow local request entry point for the Runtime pipeline.

Clients may request a published route. They cannot supply executor names,
profile/session/body bindings, module paths, shell commands, or callables.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Mapping

from services.court_intent import Intent, normalize


@dataclass(frozen=True)
class IntentRoute:
    route_id: str
    action: str
    capability: str
    target: str
    executor_name: str
    allowed_parameters: tuple[str, ...]


class LocalIntentGateway:
    def __init__(self, *, pipeline, identity_context, routes: tuple[IntentRoute, ...]):
        self._pipeline = pipeline
        self._identity = identity_context
        self._routes = self._build_routes(routes)

    def submit(self, request: Mapping[str, Any], *, now: int | None = None):
        if not isinstance(request, Mapping):
            raise TypeError("local intent request must be a mapping")

        allowed_request_keys = {"intent_id", "route_id", "parameters"}
        unknown = set(request) - allowed_request_keys
        if unknown:
            raise ValueError(f"unsupported request fields: {sorted(unknown)}")

        intent_id = _required_normalized(request, "intent_id")
        route_id = _required_normalized(request, "route_id")
        try:
            route = self._routes[route_id]
        except KeyError as exc:
            raise ValueError(f"unknown local intent route: {route_id}") from exc

        parameters = request.get("parameters", {})
        if not isinstance(parameters, Mapping):
            raise ValueError("parameters must be a mapping")
        parameter_keys = set(parameters)
        unsupported = parameter_keys - set(route.allowed_parameters)
        if unsupported:
            raise ValueError(f"unsupported parameters for route: {sorted(unsupported)}")

        body = self._identity.body
        session = self._identity.session
        requested_at = int(now if now is not None else time.time())
        intent = Intent(
            intent_id=intent_id,
            action=route.action,
            capability=route.capability,
            target=route.target,
            profile_id=session.profile.profile_id,
            session_id=session.session_id,
            body_id=body.body_id,
            surface=body.surface,
            requested_at=requested_at,
        )
        return self._pipeline.submit(
            intent=intent,
            executor_name=route.executor_name,
            parameters=dict(parameters),
            now=requested_at,
        )

    @staticmethod
    def _build_routes(routes):
        built = {}
        for route in routes:
            values = (
                route.route_id,
                route.action,
                route.capability,
                route.target,
                route.executor_name,
            )
            if any(value != normalize(value) or not value for value in values):
                raise ValueError("intent route fields must be non-empty and normalized")
            allowed = tuple(sorted(set(route.allowed_parameters)))
            if any(not isinstance(value, str) or not value or value != normalize(value) for value in allowed):
                raise ValueError("allowed parameter names must be normalized strings")
            if route.route_id in built:
                raise ValueError(f"duplicate intent route: {route.route_id}")
            built[route.route_id] = IntentRoute(
                route.route_id,
                route.action,
                route.capability,
                route.target,
                route.executor_name,
                allowed,
            )
        return built


def _required_normalized(request: Mapping[str, Any], key: str) -> str:
    value = request.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    if value != normalize(value):
        raise ValueError(f"{key} must already be normalized")
    return value
