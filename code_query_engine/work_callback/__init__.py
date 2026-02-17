from .broker import get_work_callback_broker, WorkCallbackBroker
from .policy import (
    CallbackPolicy,
    DEFAULT_CALLBACK_POLICY,
    resolve_callback_policy,
    callback_policy_from_dict,
    callback_policy_to_dict,
)


def register_work_callback_routes(*args, **kwargs):
    # Keep controller/flask dependency lazy so policy helpers can be imported
    # in lightweight contexts (e.g., unit tests) without Flask installed.
    from .controller import register_work_callback_routes as _register_work_callback_routes

    return _register_work_callback_routes(*args, **kwargs)

__all__ = [
    "WorkCallbackBroker",
    "get_work_callback_broker",
    "register_work_callback_routes",
    "CallbackPolicy",
    "DEFAULT_CALLBACK_POLICY",
    "resolve_callback_policy",
    "callback_policy_from_dict",
    "callback_policy_to_dict",
]
