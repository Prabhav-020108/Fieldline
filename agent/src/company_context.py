"""
Per-session company identity for FieldLine's Phase 5 multi-tenancy.

Each LiveKit job (one technician's call) runs inside its own asyncio Task,
starting in agent.py's entrypoint(). We work out which company that room
belongs to once, right at the top of entrypoint(), and stash it in a
contextvars.ContextVar.

Every tool file (fault_history.py, safety_procedure.py, inventory_lookup.py,
dispatch_status.py, log_job_note.py) keeps calling
`client, index_name = await get_index()` with NO arguments, exactly as in
Phase 3/4 -- moss_client.py reads the company id back out of this
ContextVar internally. That's the whole trick that lets Phase 5 add
multi-tenancy without touching a single tool file.

Why a ContextVar and not a plain global variable: a global would leak
between two technicians' calls if this worker process ever handles more
than one room at a time (entirely possible in production). ContextVars are
copied into every asyncio.Task created from the current call stack, so as
long as set_current_company() runs BEFORE session.start() in entrypoint(),
every tool call triggered by that session sees the right company -- even
while a *different* room, for a *different* company, is being served
concurrently by the same process.

Phase 7 addition: the same pattern, applied to the LiveKit room name, so
tools/*.py can tag their Moss-retrieval tracing spans (see tracing.py) with
a correlation id without agent.py having to thread it through every tool
call by hand.
"""

from contextvars import ContextVar

# "site-demo" is Company #1 -- the original Phase 1-4 demo company. Keeping
# it as the default means console mode (`uv run src/agent.py console`) and
# any ad-hoc test room that doesn't follow the "fieldline-<company_id>"
# naming convention keep working exactly as they did before Phase 5.
DEFAULT_COMPANY_ID = "site-demo"

_current_company_id: ContextVar[str] = ContextVar(
    "fieldline_current_company_id", default=DEFAULT_COMPANY_ID
)

# Phase 7: default "console" so ad-hoc console-mode runs and any code that
# executes before set_current_room_name() is called (e.g. the eval
# harness) still get a sensible, non-empty correlation id.
_current_room_name: ContextVar[str] = ContextVar(
    "fieldline_current_room_name", default="console"
)


def set_current_company(company_id: str) -> None:
    """Call once, at the top of entrypoint(), before session.start()."""
    _current_company_id.set(company_id)


def get_current_company() -> str:
    """Read from anywhere -- tools never call this directly, but
    moss_client.get_index() does, internally."""
    return _current_company_id.get()


def set_current_room_name(room_name: str) -> None:
    """Phase 7: call once, at the top of entrypoint(), alongside
    set_current_company(). Gives tracing.py's traced_stage() calls inside
    tools/*.py a stable correlation_id -- see tracing.py's module
    docstring for why this is call-level, not turn-level, granularity."""
    _current_room_name.set(room_name)


def get_current_room_name() -> str:
    """Read from anywhere -- tools call this to tag their retrieval spans
    with the right correlation id."""
    return _current_room_name.get()


def company_id_from_room_name(room_name: str) -> str:
    """Room names follow 'fieldline-<company_id>', e.g.
    'fieldline-acme-elevator' -> 'acme-elevator'. Falls back to the default
    demo company if the room name doesn't follow that convention, so a
    quick test room from the LiveKit Agent Console still works with zero
    setup."""
    prefix = "fieldline-"
    if room_name.startswith(prefix):
        candidate = room_name[len(prefix):].strip()
        if candidate:
            return candidate
    return DEFAULT_COMPANY_ID