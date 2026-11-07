"""iMessage over Sendblue (owner: TAAZ): send the verdict to the code owner, act on their reply.

Env (secrets/.env, never committed):
  SENDBLUE_API_KEY, SENDBLUE_API_SECRET   dashboard credentials (headers sb-api-key-id / sb-api-secret-key)
  SENDBLUE_FROM_NUMBER                    the shared line, required on the free plan
  SENDBLUE_WEBHOOK_SECRET                 random string; configure the webhook as
                                          https://<public-host>/api/sendblue?token=<secret>
  OWNER_PHONES                            {"owner@email": "+15551234567"}

Security, in the spirit of "easy to stop, hard to approve":
  - the webhook fails closed: no SENDBLUE_WEBHOOK_SECRET configured -> every call is rejected
  - a reply only acts if it comes from the verified phone of the PR's top owner; anyone else is ignored
  - nothing here can approve or merge; OK only answers with the GitHub link (see notify.handle_reply)
Without Sendblue keys the ConsoleNotifier is used, so the demo still runs end to end.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from .notify import Action, ConsoleNotifier, Notifier, Reply, handle_reply, parse_reply
from .schema import VerdictReport

SEND_URL = "https://api.sendblue.com/api/send-message"


class SendError(RuntimeError):
    pass


def phone_key(phone: str) -> str:
    """Last 10 digits: '+1 (555) 123-4567' and '15551234567' are the same number."""
    return re.sub(r"\D", "", phone or "")[-10:]


def owner_phones() -> dict[str, str]:
    """email (lowercased) -> phone, from OWNER_PHONES."""
    return {k.lower(): v for k, v in json.loads(os.environ.get("OWNER_PHONES") or "{}").items()}


def phone_for(email: str) -> str | None:
    return owner_phones().get((email or "").lower())


class SendblueNotifier:
    def __init__(self, key: str, secret: str, from_number: str = "", timeout_s: int = 15) -> None:
        self.key, self.secret, self.from_number, self.timeout_s = key, secret, from_number, timeout_s

    def send(self, phone: str, text: str) -> str:
        body = {"number": phone, "content": text}
        if self.from_number:
            body["from_number"] = self.from_number
        req = urllib.request.Request(
            SEND_URL,
            data=json.dumps(body).encode("utf-8"),
            # explicit User-Agent: Cloudflare in front of Sendblue rejects Python-urllib's default (403, code 1010)
            headers={"sb-api-key-id": self.key, "sb-api-secret-key": self.secret, "Content-Type": "application/json",
                     "User-Agent": "merge-gate/0.1"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                d = json.loads(r.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            raise SendError(f"Sendblue HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}") from e
        if d.get("status") in ("ERROR", "DECLINED") or d.get("error_code"):
            raise SendError(f"Sendblue rejected the message: {d.get('status')} {d.get('error_message') or ''}".strip())
        return d.get("message_handle") or d.get("status") or "sent"


def notifier_from_env() -> Notifier:
    key, secret = os.environ.get("SENDBLUE_API_KEY"), os.environ.get("SENDBLUE_API_SECRET")
    if key and secret:
        return SendblueNotifier(key, secret, os.environ.get("SENDBLUE_FROM_NUMBER", ""))
    return ConsoleNotifier()


def webhook_authorized(query_token: str | None, header_values: list[str]) -> bool:
    """Token in the webhook URL (or any header carrying it, which is how Sendblue sends its secret)."""
    secret = os.environ.get("SENDBLUE_WEBHOOK_SECRET", "")
    if len(secret) < 16:
        return False  # fail closed: no or weak secret means no webhook
    candidates = [query_token or "", *header_values]
    return any(hmac.compare_digest(c.encode("utf-8"), secret.encode("utf-8")) for c in candidates)


@dataclass
class Inbound:
    phone: str
    text: str


def parse_inbound(payload: dict) -> Inbound | None:
    """Sendblue inbound-message webhook body -> Inbound; None for our own outbound echoes."""
    if payload.get("is_outbound"):
        return None
    phone = payload.get("from_number") or payload.get("number") or ""
    return Inbound(phone=phone, text=payload.get("content") or "") if phone else None


def handle_inbound(inbound: Inbound, report: VerdictReport, pr_url: str = "") -> tuple[Action, Reply, bool]:
    """(action, reply, authorized). Only the PR's top owner, from their verified number, can act."""
    reply = parse_reply(inbound.text)
    owner = report.owners[0] if report.owners else None
    expected = phone_for(owner.email) if owner else None
    if not expected or phone_key(expected) != phone_key(inbound.phone):
        return Action("none"), reply, False
    return handle_reply(report, reply, pr_url), reply, True


# --- conversational replies ------------------------------------------------------------------------
# The ACTION (block / why / ok / false alarm) is always decided by plain code above. Muse Spark only words
# the text the owner reads, from the verdict's own facts, so the reply sounds like a person, not a template.

_FORBIDDEN = re.compile(r"\b(approv\w*|merg(ed|ing)|lgtm|ship(ped)? it)\b", re.I)


def _facts(report: VerdictReport, pr_url: str) -> str:
    ev = "\n".join(f"- [{e.severity}] {e.id}: {e.detail}" for e in report.evidence) or "- none"
    owner = report.owners[0].name if report.owners else "unknown"
    return (f"PR: {report.pr_id} {pr_url}\nVerdict (decided by plain code, not you): {report.verdict}\n"
            f"Code owner you are texting: {owner}\nEvidence:\n{ev}\nRun hash: {report.run_hash}")


def converse(report: VerdictReport, owner_text: str, action: Action, pr_url: str = "") -> str:
    """Muse-written reply for the owner. Falls back to the plain-code text on any failure or rule break."""
    fallback = action.text or "Reply BLOCK, WHY, OK or FALSE ALARM."
    try:
        from .llm import complete

        developer = (
            "You are Merge Gate, texting the engineer who wrote the code a pull request changes. "
            "Voice: savage, blunt, zero sugarcoating. Short punchy sentences, dry wit, total confidence. "
            "Say exactly what is broken and why it matters, in plain words, like a founder who has no time. "
            "Roast the CODE and the change, never the person: no insults, slurs or profanity aimed at anyone. "
            "Do not impersonate or name any real person. 1-3 sentences, no markdown, no lists, no emoji. "
            "Use ONLY the facts given; never invent a bug, number or test. If the verdict is PASS, say so plainly "
            "and don't manufacture problems. The action below has ALREADY been taken by plain code; state it, never "
            "invent another. Never say or imply the PR is approved, merged or safe to ship: approval only happens "
            "on GitHub with the owner's own login. If the owner asks something the facts can't answer, say so and "
            "tell them to reply WHY or BLOCK.")
        user = (f"{_facts(report, pr_url)}\n\nAction already taken: {action.kind}\n"
                f"Plain-code reply you are rewording: {fallback}\n\nOwner's message: {owner_text[:500]}")
        text = complete(developer, user, temperature=0.4, timeout_s=25, retries=1, use_cache=False).strip()
    except Exception:  # noqa: BLE001 - the plain-code text is always a safe reply
        return fallback
    if not text or len(text) > 700 or _FORBIDDEN.search(text):
        return fallback
    if action.kind == "block_pr" and "block" not in text.lower():
        return fallback  # a BLOCK confirmation must say so explicitly
    return text
