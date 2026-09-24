from parcel import status


def test_status_is_queued():
    assert status("P1") == {"parcel_id": "P1", "state": "queued"}
