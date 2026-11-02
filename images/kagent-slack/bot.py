"""Slack <-> kagent bridge: @mention (or DM) the bot, it asks one A2A agent.

Each Slack thread maps to one kagent conversation through a context id
derived from the thread, so threads keep their context across restarts
without any stored state.
"""

import json
import logging
import os
import re
import urllib.request
import uuid
from dataclasses import dataclass

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient

logger = logging.getLogger(__name__)

# chat.postMessage caps markdown_text at 12,000 characters.
SLACK_MAX = 12_000
_MENTION = re.compile(r"<@[A-Z0-9]+>")
_FAILED = {"failed", "rejected", "canceled"}


class AgentError(Exception):
    """The agent call failed or the task ended unsuccessfully."""


@dataclass(frozen=True, slots=True)
class Reply:
    text: str
    needs_input: bool


def context_id(channel: str, thread_ts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"slack:{channel}:{thread_ts}"))


def strip_mention(text: str) -> str:
    return " ".join(_MENTION.sub(" ", text).split())


def is_allowed(user: str, allowed: frozenset[str]) -> bool:
    return user in allowed


def build_request(text: str, ctx: str) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "messageId": str(uuid.uuid4()),
                "contextId": ctx,
                "parts": [{"kind": "text", "text": text}],
            }
        },
    }


def _text(parts: list[dict[str, object]]) -> str:
    return "\n".join(str(p["text"]) for p in parts if p.get("kind") == "text")


def parse_result(resp: dict[str, object]) -> Reply:
    if "error" in resp:
        raise AgentError(str(resp["error"]))
    result = resp.get("result")
    if not isinstance(result, dict):
        raise AgentError(f"no result in response: {resp}")
    if result.get("kind") == "message":
        return Reply(text=_text(result.get("parts", [])), needs_input=False)
    status = result.get("status", {})
    state = status.get("state")
    status_text = _text((status.get("message") or {}).get("parts", []))
    if state in _FAILED:
        raise AgentError(status_text or f"task {state}")
    if state == "input-required":
        return Reply(text=status_text, needs_input=True)
    artifacts = result.get("artifacts", [])
    text = "\n".join(_text(a.get("parts", [])) for a in artifacts) or status_text
    return Reply(text=text, needs_input=False)


def render(reply: Reply, ui_chat_url: str, ctx: str) -> list[str]:
    text = reply.text
    if reply.needs_input:
        text += (
            f"\n\nThe agent is waiting on you. Answer in the kagent UI: "
            f"{ui_chat_url}/{ctx}"
        )
    if not text.strip():
        return ["_(the agent returned no text)_"]
    return [text[i : i + SLACK_MAX] for i in range(0, len(text), SLACK_MAX)]


def ask(a2a_url: str, text: str, ctx: str) -> Reply:
    body = json.dumps(build_request(text, ctx)).encode()
    req = urllib.request.Request(a2a_url, body, {"Content-Type": "application/json"})
    # No timeout: homelab-agent turns can legitimately run for a long time.
    with urllib.request.urlopen(req) as r:
        return parse_result(json.load(r))


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    a2a_url = os.environ["KAGENT_A2A_URL"]
    ui_chat_url = os.environ["KAGENT_UI_CHAT_URL"].rstrip("/")
    allowed = frozenset(os.environ["ALLOWED_USER_IDS"].replace(",", " ").split())
    app = App(token=os.environ["SLACK_BOT_TOKEN"])

    def handle(event: dict[str, str], client: WebClient) -> None:
        channel, ts = event["channel"], event["ts"]
        thread_ts = event.get("thread_ts") or ts
        if not is_allowed(event.get("user", ""), allowed):
            logger.warning("ignoring user %s", event.get("user"))
            return
        text = strip_mention(event.get("text", ""))
        if not text:
            return
        ctx = context_id(channel, thread_ts)
        client.reactions_add(channel=channel, timestamp=ts, name="eyes")
        try:
            chunks = render(ask(a2a_url, text, ctx), ui_chat_url, ctx)
        except Exception as err:
            logger.exception("agent call failed for context %s", ctx)
            chunks = [f"Agent call failed: `{err}`"]
        for chunk in chunks:
            client.chat_postMessage(
                channel=channel, thread_ts=thread_ts, markdown_text=chunk
            )
        client.reactions_remove(channel=channel, timestamp=ts, name="eyes")

    @app.event("app_mention")
    def on_mention(event: dict[str, str], client: WebClient) -> None:
        handle(event, client)

    @app.event("message")
    def on_message(event: dict[str, str], client: WebClient) -> None:
        # DMs only; skip edits, joins and the bot's own posts (subtype/bot_id).
        if event.get("channel_type") != "im" or "subtype" in event:
            return
        if "bot_id" in event:
            return
        handle(event, client)

    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()


if __name__ == "__main__":
    main()
