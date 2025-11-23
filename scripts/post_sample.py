from __future__ import annotations

import uuid

import httpx

PAYLOAD_TEMPLATE = {
    "first_name": "Auto",
    "gender": "F",
    "birth_date": "1995-01-01",
    "lost_timestamp": "2024-01-01T12:00:00Z",
    "lost_location": "QA City",
    "details": "autotest",
    "status": "active",
}


def main() -> None:
    payload = PAYLOAD_TEMPLATE | {"last_name": uuid.uuid4().hex[:8]}
    resp = httpx.post("http://localhost:40140/report_person/", json=payload, timeout=10)
    resp.raise_for_status()
    print(resp.json())


if __name__ == "__main__":
    main()
