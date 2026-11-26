"""Webhook server: transcript in, coaching result out.

POST /webhook   {"call_id": "...", "transcript": "...", "callback_url": "optional"}
GET  /health

Security:
- If COACH_WEBHOOK_SECRET is set, inbound requests must carry
  X-Signature: sha256=<hex HMAC of the raw body>. Outbound callbacks are
  signed the same way, so the receiver can verify them.
"""
import hashlib
import hmac
import json
import os
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

from .scorer import get_scorer, load_rubric


def sign(secret, body):
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify(secret, body, header):
    if not secret:
        return True
    return bool(header) and hmac.compare_digest(sign(secret, body), header)


def deliver(url, result, secret):
    body = json.dumps(result).encode()
    headers = {"content-type": "application/json"}
    if secret:
        headers["X-Signature"] = sign(secret, body)
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status


class Handler(BaseHTTPRequestHandler):
    scorer = None
    rubric = None
    secret = None

    def _send(self, code, obj):
        body = json.dumps(obj, indent=2).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, {"status": "ok", "scorer": self.scorer.name})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/webhook":
            return self._send(404, {"error": "not found"})
        length = int(self.headers.get("content-length", 0))
        raw = self.rfile.read(length)
        if not verify(self.secret, raw, self.headers.get("X-Signature")):
            return self._send(401, {"error": "bad signature"})
        try:
            payload = json.loads(raw)
            transcript = payload["transcript"]
        except (ValueError, KeyError):
            return self._send(400, {"error": "expected JSON with a 'transcript' field"})

        result = self.scorer.score(transcript, self.rubric)
        result["call_id"] = payload.get("call_id")
        callback = payload.get("callback_url") or os.environ.get("COACH_OUTBOUND_URL")
        if callback:
            try:
                result["delivered"] = deliver(callback, result, self.secret)
            except Exception as exc:  # report, don't fail the scoring
                result["delivered"] = f"failed: {exc}"
        self._send(200, result)

    def log_message(self, fmt, *args):
        pass


def serve(port=8080, scorer_kind=None):
    Handler.scorer = get_scorer(scorer_kind)
    Handler.rubric = load_rubric()
    Handler.secret = os.environ.get("COACH_WEBHOOK_SECRET")
    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"Listening on http://127.0.0.1:{port} (scorer={Handler.scorer.name}, "
          f"signature check={'on' if Handler.secret else 'off'})")
    server.serve_forever()
