"""
Tests for company_context.py -- how a call is routed to the right company.

The most important property: two calls happening at the same time for two
different companies must never see each other's company (multi-tenancy).

    uv run pytest tests/test_company_context.py -v
"""

import asyncio

import pytest

import company_context


@pytest.mark.parametrize(
    ("room_name", "expected_company"),
    [
        ("fieldline-site-demo", "site-demo"),
        ("fieldline-acme-elevator", "acme-elevator"),
        ("fieldline-my-new-co-2", "my-new-co-2"),
    ],
)
def test_company_id_is_read_from_the_room_name(room_name, expected_company):
    assert company_context.company_id_from_room_name(room_name) == expected_company


@pytest.mark.parametrize(
    "room_name",
    ["", "console", "some-random-room", "fieldline-", "fieldline-   ", "FIELDLINE-acme"],
)
def test_rooms_that_do_not_follow_the_convention_fall_back_to_the_demo_company(room_name):
    assert company_context.company_id_from_room_name(room_name) == "site-demo"


async def test_concurrent_calls_do_not_see_each_others_company():
    seen: dict[str, str] = {}

    async def _call(company_id: str, delay: float) -> None:
        company_context.set_current_company(company_id)
        await asyncio.sleep(delay)  # let the other call run in between
        seen[company_id] = company_context.get_current_company()

    await asyncio.gather(_call("site-demo", 0.05), _call("acme-elevator", 0.01))

    assert seen == {"site-demo": "site-demo", "acme-elevator": "acme-elevator"}


async def test_concurrent_calls_do_not_see_each_others_role():
    seen: dict[str, str] = {}

    async def _call(name: str, role: str, delay: float) -> None:
        company_context.set_current_role(role)
        await asyncio.sleep(delay)
        seen[name] = company_context.get_current_role()

    await asyncio.gather(_call("a", "dispatcher", 0.05), _call("b", "technician", 0.01))

    assert seen == {"a": "dispatcher", "b": "technician"}


async def test_a_fresh_call_defaults_to_least_privilege_and_the_console_room():
    async def _fresh_call() -> tuple[str, str]:
        return company_context.get_current_role(), company_context.get_current_room_name()

    role, room = await asyncio.create_task(_fresh_call())

    assert role == "technician"
    assert room == "console"
