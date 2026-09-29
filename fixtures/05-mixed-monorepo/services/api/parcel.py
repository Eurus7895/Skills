def status(parcel_id: str) -> dict[str, str]:
    return {"parcel_id": parcel_id, "state": "queued"}
