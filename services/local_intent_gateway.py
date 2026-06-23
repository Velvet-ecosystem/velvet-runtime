# SPDX-License-Identifier: GPL-3.0-only
"""Narrow local request entry point for the Runtime pipeline."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from services.court_intent import Intent, normalize
from services.request_origin import RequestOrigin, local_origin


@dataclass(frozen=True)
class IntentRoute:
    route_id: str
    action: str
    capability: str
    target: str
    executor_name: str
    allowed_parameters: tuple[str, ...]


class LocalIntentGateway:
    def __init__(
        self,
        *,
        pipeline,
        identity_context,
        routes: tuple[IntentRoute, ...],
        origin_observer: Callable[[RequestOrigin], None] | None = None,
    ):
        self._pipeline = pipeline
        self._identity = identity_context
        self._routes = self._build_routes(routes)
        self._origin_observer = origin_observer

    def submit(self, request: Mapping[str, Any], *, now: int | None = None):
        received_at = int(now if now is not None else time.time())
        origin = local_origin(
            peer_id="runtime-in-process",
            transport_id="python-call",
            received_at=received_at,
        )
        return self.submit_from_origin(request, origin=origin, now=received_at)

    def submit_from_origin(
        self,
        request: Mapping[str, Any],
        *,
        origin: RequestOrigin,
        now: int | None = None,
    ):
        if not isinstance(origin, RequestOrigin):
            raise TypeError("origin must be RequestOrigin")
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
        unsupported = set(parameters) - set(route.allowed_parameters)
        if unsupported:
            raise ValueError(f"unsupported parameters for route: {sorted(unsupported)}")

        requested_at = int(now if now is not None else origin.received_at)
        if requested_at < origin.received_at:
            raise ValueError("request time cannot precede origin time")

        if self._origin_observer is not None:
            self._origin_observer(origin)

        body = self._identity.body
        session = self._identity.session
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
