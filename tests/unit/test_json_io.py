"""Concurrent readers and writers always observe complete project JSON documents."""

import json
from concurrent.futures import ThreadPoolExecutor

from carma.model.json_io import read_json, write_json


def test_concurrent_atomic_json_writes(tmp_path):
    path = tmp_path / "state.json"
    write_json(path, {"writer": -1, "payload": "initial"})

    def writer(number):
        for _ in range(12):
            write_json(path, {"writer": number, "payload": str(number) * 8000})

    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = [pool.submit(writer, number) for number in range(4)]
        while not all(job.done() for job in jobs):
            try:
                data = read_json(path)
            except PermissionError:  # Windows may briefly deny a reader during replacement.
                continue
            assert data["payload"] == ("initial" if data["writer"] == -1 else str(data["writer"]) * 8000)
        for job in jobs:
            job.result()
    assert json.loads(path.read_text(encoding="utf-8"))["writer"] in range(4)
    assert not list(tmp_path.glob(".*.tmp"))
