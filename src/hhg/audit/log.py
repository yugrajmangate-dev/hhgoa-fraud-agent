"""Append-only, hash-chained audit log (JSONL). Each event's hash covers the previous hash,
so any edit or deletion breaks verification."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

GENESIS = "0" * 64


class AuditLog:
    def __init__(self, path: Path, run_id: str, case_id: str):
        self.path, self.run_id, self.case_id = path, run_id, case_id
        path.parent.mkdir(parents=True, exist_ok=True)
        self.prev, self.seq, self.step = GENESIS, 0, 0
        path.write_text("", encoding="utf-8")

    def enter_state(self, state: str, detail: dict = None) -> int:
        self.step += 1
        self.append("state", {"state": state, "step": self.step, **(detail or {})})
        return self.step

    def append(self, event: str, payload: dict):
        self.seq += 1
        body = {"seq": self.seq, "wall": datetime.now(timezone.utc).isoformat(), "run_id": self.run_id,
                "case_id": self.case_id, "event": event, "payload": payload, "prev": self.prev}
        digest = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
        body["hash"] = digest
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(body, default=str) + "\n")
        self.prev = digest


def verify(path: Path) -> tuple:
    prev = GENESIS
    lines = path.read_text(encoding="utf-8").splitlines()
    for n, line in enumerate(lines, 1):
        body = json.loads(line)
        digest = body.pop("hash")
        if body["prev"] != prev or hashlib.sha256(
                json.dumps(body, sort_keys=True, default=str).encode()).hexdigest() != digest:
            return False, n
        prev = digest
    return True, len(lines)
