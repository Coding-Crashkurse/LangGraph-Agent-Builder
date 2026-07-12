"""Full A2A input-required round trip against a running lab server (SPEC §13/04).

a2a-sdk 1.x / protocol v1.0: REST ``message:send``, ProtoJSON flat parts,
``TASK_STATE_*`` enum names, Task under ``response.json()["task"]``.

Usage: python client.py [server-base] [agent-slug]
       (defaults: http://127.0.0.1:8010 hitl-approval)
"""

from __future__ import annotations

import json
import sys
import uuid

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010"
SLUG = sys.argv[2] if len(sys.argv) > 2 else "hitl-approval"
A2A = f"{BASE}/a2a/{SLUG}"


def send(message: dict) -> dict:
    response = httpx.post(f"{A2A}/message:send", json={"message": message}, timeout=60)
    if response.status_code != 200:
        body = response.json()
        reason = body.get("error", {}).get("details", [{}])[0].get("reason", body)
        sys.exit(f"A2A error {response.status_code}: {reason}")
    return response.json()["task"]


def main() -> None:
    card = httpx.get(f"{A2A}/.well-known/agent-card.json", timeout=10).json()
    print(f"agent: {card['name']} v{card['version']} — {card['description']}")

    task = send({
        "role": "ROLE_USER", "messageId": str(uuid.uuid4()),
        "parts": [{"text": "draft a reply to the refund request"}],
    })
    print(f"task {task['id']} → {task['status']['state']}")
    assert task["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"
    prompt = next(p["text"] for p in task["status"]["message"]["parts"] if "text" in p)
    payload = next(p["data"] for p in task["status"]["message"]["parts"] if "data" in p)
    print(f"agent asks: {prompt}  options={payload['options']}")

    answer = input("approve/reject> ").strip() or "approve"
    done = send({
        "role": "ROLE_USER", "messageId": str(uuid.uuid4()),
        "taskId": task["id"], "contextId": task["contextId"],
        "parts": [{"data": {"decision": answer}}],
    })
    print(f"task → {done['status']['state']}")
    for artifact in done.get("artifacts") or []:
        for part in artifact.get("parts", []):
            if "text" in part:
                print("artifact:", part["text"])
    print(json.dumps(done["status"], indent=2)[:400])


if __name__ == "__main__":
    main()
