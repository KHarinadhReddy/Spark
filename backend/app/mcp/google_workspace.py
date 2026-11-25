from __future__ import annotations

import base64
import json
import os
import threading
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Any

import httpx

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

SCOPES = (
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/drive.readonly",
)


class GoogleAuthError(Exception):
    pass


class GoogleTokenStore:
    """Stores a single user's OAuth tokens locally (demo) — never in the browser."""

    def __init__(
        self,
        token_path: Path,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
    ) -> None:
        self.token_path = Path(token_path)
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self._state_values: set[str] = set()
        self._lock = threading.Lock()

    def _write(self, payload: dict[str, Any]) -> None:
        """Write the token atomically so a crash cannot leave a truncated file."""
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.token_path.with_suffix(self.token_path.suffix + ".tmp")
        temp.write_text(json.dumps(payload), encoding="utf-8")
        try:
            os.chmod(temp, 0o600)
        except OSError:
            pass
        os.replace(temp, self.token_path)

    @property
    def connected(self) -> bool:
        return bool(self.client_id and self.client_secret) and self.token_path.exists()

    def authorize_url(self, state: str) -> str:
        from urllib.parse import urlencode

        self._state_values.add(state)
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": state,
        }
        return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

    def check_state(self, state: str) -> bool:
        if state in self._state_values:
            self._state_values.discard(state)
            return True
        return False

    def exchange(self, code: str) -> dict[str, Any]:
        with httpx.Client(timeout=20) as client:
            response = client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": self.redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
        if response.status_code >= 400:
            raise GoogleAuthError(f"token exchange failed: {response.text[:200]}")
        payload = response.json()
        payload["expires_at"] = (
            datetime.now(timezone.utc) + timedelta(seconds=int(payload.get("expires_in", 3600)))
        ).isoformat()
        self._write(payload)
        return payload

    def load(self) -> dict[str, Any]:
        if not self.token_path.exists():
            raise GoogleAuthError("Google account is not connected")
        return json.loads(self.token_path.read_text(encoding="utf-8"))

    def access_token(self) -> str:
        with self._lock:
            token = self.load()
            expires_at = token.get("expires_at")
            if expires_at:
                expiry = datetime.fromisoformat(expires_at)
                if expiry - datetime.now(timezone.utc) < timedelta(seconds=60):
                    token = self._refresh(token)
            return token["access_token"]

    def _refresh(self, token: dict[str, Any]) -> dict[str, Any]:
        refresh_token = token.get("refresh_token")
        if not refresh_token:
            raise GoogleAuthError("refresh token missing; reconnect Google")
        with httpx.Client(timeout=20) as client:
            response = client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        if response.status_code >= 400:
            raise GoogleAuthError(f"token refresh failed: {response.text[:200]}")
        refreshed = response.json()
        token.update(refreshed)
        token["expires_at"] = (
            datetime.now(timezone.utc)
            + timedelta(seconds=int(refreshed.get("expires_in", 3600)))
        ).isoformat()
        self._write(token)
        return token

    def disconnect(self) -> None:
        self.token_path.unlink(missing_ok=True)


class GoogleWorkspace:
    """Live Google Calendar + Gmail + Drive adapter using plain REST + OAuth tokens."""

    def __init__(self, tokens: GoogleTokenStore, timezone_name: str = "Asia/Kolkata") -> None:
        self.tokens = tokens
        self.timezone_name = timezone_name

    def _client(self) -> httpx.Client:
        return httpx.Client(
            timeout=25,
            headers={"Authorization": f"Bearer {self.tokens.access_token()}"},
        )

    @staticmethod
    def _error(response: httpx.Response) -> None:
        if response.status_code >= 400:
            raise RuntimeError(f"Google API {response.status_code}: {response.text[:200]}")

    # ------------------------------------------------------------ calendar API
    def list_events(self, start: str | None = None, end: str | None = None, limit: int = 20) -> dict[str, Any]:
        params = {
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": int(limit),
        }
        if start:
            params["timeMin"] = start
        if end:
            params["timeMax"] = end
        with self._client() as client:
            response = client.get(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                params=params,
            )
        self._error(response)
        events = []
        for item in response.json().get("items", []):
            events.append(
                {
                    "id": item["id"],
                    "summary": item.get("summary", "(untitled)"),
                    "description": item.get("description", ""),
                    "location": item.get("location", ""),
                    "start": item.get("start", {}).get("dateTime") or item.get("start", {}).get("date", ""),
                    "end": item.get("end", {}).get("dateTime") or item.get("end", {}).get("date", ""),
                    "status": item.get("status", ""),
                    "html_link": item.get("htmlLink", ""),
                    "provider": "google",
                }
            )
        return {"events": events, "count": len(events)}

    def create_event(
        self,
        summary: str,
        start: str,
        end: str,
        description: str = "",
        location: str = "",
    ) -> dict[str, Any]:
        body = {
            "summary": summary,
            "description": description,
            "location": location,
            "start": {"dateTime": start, "timeZone": self.timezone_name},
            "end": {"dateTime": end, "timeZone": self.timezone_name},
        }
        with self._client() as client:
            response = client.post(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events", json=body
            )
        self._error(response)
        item = response.json()
        return {
            "event": {
                "id": item["id"],
                "summary": item.get("summary", summary),
                "start": start,
                "end": end,
                "html_link": item.get("htmlLink", ""),
                "provider": "google",
            }
        }

    def delete_event(self, event_id: str) -> dict[str, Any]:
        with self._client() as client:
            response = client.delete(
                f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{event_id}"
            )
        if response.status_code not in (200, 204, 404):
            self._error(response)
        return {"deleted": response.status_code != 404, "event_id": event_id}

    # --------------------------------------------------------------- gmail API
    def search_emails(self, query: str = "", limit: int = 10) -> dict[str, Any]:
        params = {"maxResults": int(limit)}
        if query:
            params["q"] = query
        with self._client() as client:
            response = client.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages", params=params
            )
        self._error(response)
        emails = []
        for ref in response.json().get("messages", []):
            email = self._fetch_email(ref["id"], summary_only=True)
            emails.append(email)
        return {"emails": emails, "count": len(emails)}

    def list_message_ids(
        self,
        query: str = "",
        limit: int = 50,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "maxResults": min(max(int(limit), 1), 500),
            "includeSpamTrash": "false",
        }
        if query:
            params["q"] = query
        if page_token:
            params["pageToken"] = page_token
        with self._client() as client:
            response = client.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages", params=params
            )
        self._error(response)
        payload = response.json()
        return {
            "ids": [item["id"] for item in payload.get("messages", [])],
            "next_page_token": payload.get("nextPageToken"),
            "result_size_estimate": payload.get("resultSizeEstimate", 0),
        }

    def get_message(self, message_id: str) -> dict[str, Any]:
        return self._fetch_email(message_id, summary_only=False)

    def get_attachment_text(self, message: dict[str, Any], max_bytes: int = 2_000_000) -> str:
        """Best-effort text extraction from PDF/text attachments on a message payload.

        The caller passes the raw Gmail message payload, not the simplified dict.
        """
        import io

        texts: list[str] = []

        def walk(part: dict[str, Any]) -> None:
            body = part.get("body", {})
            filename = part.get("filename", "")
            mime = part.get("mimeType", "")
            if body.get("attachmentId") and (
                mime == "application/pdf" or mime.startswith("text/") or filename.lower().endswith(".pdf")
            ):
                try:
                    with self._client() as client:
                        response = client.get(
                            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/"
                            f"{message['id']}/attachments/{body['attachmentId']}"
                        )
                    self._error(response)
                    raw = base64.urlsafe_b64decode(response.json().get("data", "") + "===")
                    raw = raw[:max_bytes]
                    if mime == "application/pdf" or filename.lower().endswith(".pdf"):
                        try:
                            import pypdf

                            reader = pypdf.PdfReader(io.BytesIO(raw))
                            texts.append("\n".join(page.extract_text() or "" for page in reader.pages))
                        except Exception:
                            texts.append("")
                    else:
                        texts.append(raw.decode("utf-8", "ignore"))
                except Exception:
                    pass
            for child in part.get("parts", []):
                walk(child)

        walk(message.get("payload", {}))
        return "\n".join(text for text in texts if text).strip()

    def _fetch_email(self, email_id: str, summary_only: bool = False) -> dict[str, Any]:
        with self._client() as client:
            response = client.get(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{email_id}",
                params={"format": "full"},
            )
        self._error(response)
        message = response.json()
        headers = {
            item["name"].lower(): item["value"]
            for item in message.get("payload", {}).get("headers", [])
        }
        sender_email = parseaddr(headers.get("from", ""))[1] or headers.get("from", "")
        sender_name = parseaddr(headers.get("from", ""))[0] or sender_email
        body = self._extract_body(message.get("payload", {}))
        result = {
            "id": message["id"],
            "thread_id": message.get("threadId", message["id"]),
            "from": sender_email,
            "from_name": sender_name,
            "to": headers.get("to", "me"),
            "subject": headers.get("subject", "(no subject)"),
            "date": self._normalise_date(headers.get("date", "")),
            "snippet": message.get("snippet", ""),
            "labels": message.get("labelIds", []),
            "unread": "UNREAD" in message.get("labelIds", []),
            "flags": [],
        }
        if not summary_only:
            result["body"] = body
        return result

    def read_email(self, email_id: str) -> dict[str, Any]:
        return self._fetch_email(email_id, summary_only=False)

    @staticmethod
    def _extract_body(payload: dict[str, Any]) -> str:
        def walk(part: dict[str, Any]) -> str:
            if part.get("body", {}).get("data"):
                data = part["body"]["data"]
                try:
                    return base64.urlsafe_b64decode(data + "===").decode("utf-8", "ignore")
                except Exception:
                    return ""
            for child in part.get("parts", []):
                text = walk(child)
                if text:
                    return text
            return ""

        return walk(payload)

    @staticmethod
    def _normalise_date(raw: str) -> str:
        try:
            return parsedate_to_datetime(raw).isoformat()
        except Exception:
            return datetime.now(timezone.utc).isoformat()

    def create_draft(self, to: str, subject: str, body: str) -> dict[str, Any]:
        import base64
        from email.message import EmailMessage

        message = EmailMessage()
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        encoded = base64.urlsafe_b64encode(message.as_bytes()).decode()
        with self._client() as client:
            response = client.post(
                "https://gmail.googleapis.com/gmail/v1/users/me/drafts",
                json={"message": {"raw": encoded}},
            )
        self._error(response)
        draft = response.json()
        return {
            "draft": {
                "id": draft.get("id", ""),
                "to": to,
                "subject": subject,
                "body": body,
                "updated": datetime.now().astimezone().isoformat(timespec="seconds"),
                "provider": "google",
            }
        }

    def delete_draft(self, draft_id: str) -> dict[str, Any]:
        with self._client() as client:
            response = client.delete(
                f"https://gmail.googleapis.com/gmail/v1/users/me/drafts/{draft_id}"
            )
        if response.status_code not in (200, 204, 404):
            self._error(response)
        return {"deleted": response.status_code != 404, "draft_id": draft_id}

    # --------------------------------------------------------------- drive API
    def search_files(self, query: str = "", limit: int = 10) -> dict[str, Any]:
        params = {
            "pageSize": int(limit),
            "fields": "files(id,name,mimeType,modifiedTime,webViewLink)",
        }
        if query:
            safe = query.replace("'", "\\'")
            params["q"] = f"name contains '{safe}' and trashed = false"
        with self._client() as client:
            response = client.get(
                "https://www.googleapis.com/drive/v3/files", params=params
            )
        self._error(response)
        files = [
            {
                "id": item["id"],
                "name": item.get("name", ""),
                "mime_type": item.get("mimeType", ""),
                "modified": item.get("modifiedTime", ""),
                "web_link": item.get("webViewLink", ""),
                "content": "",
            }
            for item in response.json().get("files", [])
        ]
        return {"files": files, "count": len(files)}

    def read_file(self, file_id: str) -> dict[str, Any]:
        with self._client() as client:
            meta = client.get(
                f"https://www.googleapis.com/drive/v3/files/{file_id}",
                params={"fields": "id,name,mimeType,modifiedTime,webViewLink"},
            )
            self._error(meta)
            info = meta.json()
            content = ""
            if info.get("mimeType", "").startswith("application/vnd.google-apps"):
                export = client.get(
                    f"https://www.googleapis.com/drive/v3/files/{file_id}/export",
                    params={"mimeType": "text/plain"},
                )
                if export.status_code < 400:
                    content = export.text
            else:
                media = client.get(
                    f"https://www.googleapis.com/drive/v3/files/{file_id}",
                    params={"alt": "media"},
                )
                if media.status_code < 400:
                    content = media.text[:20000]
        return {
            "id": info["id"],
            "name": info.get("name", ""),
            "mime_type": info.get("mimeType", ""),
            "modified": info.get("modifiedTime", ""),
            "web_link": info.get("webViewLink", ""),
            "content": content,
            "flags": [],
        }
