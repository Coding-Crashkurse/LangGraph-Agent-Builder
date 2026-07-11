"""Full A2A input-required round trip against a running lab server (SPEC §13/04).

Usage: python client.py [server-base] [agent-slug]
       (defaults: http://127.0.0.1:8000 hitl-approval)
"""

from __future__ import annotations

import json
import sys
import uuid

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
SLUG = sys.argv[2] if len(sys.argv) > 2 else "hitl-approval"
ENDPOINT = f"{BASE}/a2a/{SLUG}/"


def rpc(method: str, params: dict) -> dict:
    response = httpx.post(
        ENDPOINT,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        timeout=60,
    )
    response.raise_for_status()
    body = response.json()
    if "error" in body:
        sys.exit(f"A2A error {body['error']['code']}: {body['error']['message']}")
    return body["result"]


def main() -> None:
    card = httpx.get(f"{BASE}/a2a/{SLUG}/.well-known/agent-card.json", timeout=10).json()
    print(f"agent: {card['name']} v{card['version']} — {card['description']}")

    task = rpc("message/send", {"message": {
        "role": "user", "messageId": str(uuid.uuid4()),
        "parts": [{"kind": "text", "text": "draft a reply to the refund request"}],
    }})
    print(f"task {task['id']} → {task['status']['state']}")
    assert task["status"]["state"] == "input-required"
    prompt = next(p["text"] for p in task["status"]["message"]["parts"]
                  if p["kind"] == "text")
    payload = next(p["data"] for p in task["status"]["message"]["parts"]
                   if p["kind"] == "data")
    print(f"agent asks: {prompt}  options={payload['options']}")

    answer = input("approve/reject> ").strip() or "approve"
    done = rpc("message/send", {"message": {
        "role": "user", "messageId": str(uuid.uuid4()),
        "taskId": task["id"], "contextId": task["contextId"],
        "parts": [{"kind": "data", "data": {"decision": answer}}],
    }})
    print(f"task → {done['status']['state']}")
    for artifact in done.get("artifacts") or []:
        for part in artifact.get("parts", []):
            if part.get("kind") == "text":
                print("artifact:", part["text"])
    print(json.dumps(done["status"], indent=2)[:400])


if __name__ == "__main__":
    main()
