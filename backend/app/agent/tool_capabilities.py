"""Execution guarantees, separate from authorization and tool availability."""
from enum import Enum


class CancellationCapability(str, Enum):
    COOPERATIVE_CANCEL = 'COOPERATIVE_CANCEL'
    PROCESS_TERMINABLE = 'PROCESS_TERMINABLE'
    TRANSACTION_BOUNDED = 'TRANSACTION_BOUNDED'
    NON_CANCELLABLE = 'NON_CANCELLABLE'


PROCESS_READ_TOOLS = frozenset({
    'list_delivery_demands', 'get_vehicle_attendance', 'list_dispatch_plans',
    'get_dispatch_plan_detail', 'get_unassigned_demands', 'validate_dispatch_plan',
    'list_vehicles', 'list_drivers', 'list_transport_tasks', 'get_daily_exceptions',
    'list_exception_cases', 'analyze_capacity', 'preview_dispatch_candidate',
})


def capability(definition, *, process_enabled=False, timeout_seconds=30):
    """Unknown adapters fail closed; never advertise a thread as terminable."""
    if not definition.read_only:
        kind = CancellationCapability.TRANSACTION_BOUNDED
    elif definition.name in PROCESS_READ_TOOLS and process_enabled:
        kind = CancellationCapability.PROCESS_TERMINABLE
    else:
        kind = CancellationCapability.NON_CANCELLABLE
    return dict(tool=definition.name, capability=kind.value,
                timeout_seconds=timeout_seconds if kind == CancellationCapability.PROCESS_TERMINABLE else None,
                requested_timeout_seconds=timeout_seconds,
                grace_seconds=.5 if kind == CancellationCapability.PROCESS_TERMINABLE else None,
                hard_termination=kind == CancellationCapability.PROCESS_TERMINABLE,
                external_side_effects=not definition.read_only,
                automatic_write_retry=False, late_result='DISCARD_AFTER_TERMINAL',
                scope='Worker process tree only; remote SQL subject to server statement timeout'
                if kind == CancellationCapability.PROCESS_TERMINABLE else
                'Commit boundary' if not definition.read_only else 'No hard cancellation guarantee')
