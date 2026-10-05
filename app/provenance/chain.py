"""查询证据链"""
import json
import hashlib
from datetime import datetime


class ProvenanceChain:
    def __init__(self, session_id: str, user_id: str = "anonymous"):
        self.chain_id = hashlib.md5(
            f"{session_id}:{user_id}:{datetime.now().isoformat()}".encode()
        ).hexdigest()[:16]
        self.session_id = session_id
        self.user_id = user_id
        self.steps = []

    def record(self, step_type: str, data: dict):
        self.steps.append({
            "step": len(self.steps) + 1,
            "type": step_type,
            "timestamp": datetime.now().isoformat(),
            "data": data,
        })

    def to_dict(self) -> dict:
        return {
            "chain_id": self.chain_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "steps": self.steps,
        }

    def to_jsonl(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)