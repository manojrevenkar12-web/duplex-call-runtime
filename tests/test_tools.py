import datetime as dt

from dcr.agent.tools import ToolBox

MON = dt.date(2026, 10, 26)


def test_an_explicit_calendar_has_exactly_the_slots_given_taken() -> None:
    tb = ToolBox(MON, taken=["2026-10-27 11:00"])
    assert tb.call("check_availability", {"service": "haircut", "date": "2026-10-27", "time": "11:00"})["available"] is False
    assert tb.call("check_availability", {"service": "haircut", "date": "2026-10-27", "time": "11:30"})["available"] is True


def test_the_demo_calendar_is_reproducible_and_partly_booked() -> None:
    a, b = ToolBox(MON), ToolBox(MON)
    assert a.taken == b.taken
    slots = sum(len(ToolBox.slots(MON + dt.timedelta(days=d))) for d in range(8))
    assert 0.2 < len(a.taken) / slots < 0.45


def test_booking_needs_a_free_slot_in_opening_hours() -> None:
    tb = ToolBox(MON, taken=[])
    ok = tb.call(
        "book_appointment", {"service": "beard", "date": "2026-10-30", "time": "10:30", "name": "Tom Becker", "phone": "01521234567"}
    )
    assert ok.get("booked") and tb.bookings[0].name == "Tom Becker"
    again = tb.call("book_appointment", {"service": "beard", "date": "2026-10-30", "time": "10:30", "name": "X Y", "phone": "0150000000"})
    assert not again.get("booked")
    sunday = tb.call("check_availability", {"service": "haircut", "date": "2026-11-01", "time": "10:00"})
    assert sunday["available"] is False
