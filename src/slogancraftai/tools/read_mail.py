import base64
import json
import logging
from email.message import Message

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError as HTTPError

from ..security import SecurityError


class GmailTool:
    SCOPES = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/calendar",
    ]

    def __init__(self, settings, token_data=None, save_token=None):
        self.settings = settings
        self.token_data = token_data
        self.save_token = save_token
        self.creds = None
        self.email_service = None
        self.calendar_service = None

    def _flow(self):
        config = {
            "web": {
                "client_id": self.settings.provider_value("GOOGLE_CLIENT_ID"),
                "client_secret": self.settings.provider_value("GOOGLE_CLIENT_SECRET"),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [self.settings.redirect_uri("gmail")],
            }
        }
        flow = InstalledAppFlow.from_client_config(
            config, self.SCOPES, autogenerate_code_verifier=False
        )
        flow.redirect_uri = self.settings.redirect_uri("gmail")
        return flow

    def get_auth_url(self, state):
        url, _ = self._flow().authorization_url(
            state=state, prompt="consent", access_type="offline"
        )
        return url

    def authenticate_gmail(self, user_token=None):
        token = user_token or self.token_data
        if not token:
            raise SecurityError("Connect Gmail before using this operation.")
        try:
            self.creds = Credentials.from_authorized_user_info(token, self.SCOPES)
            if not self.creds.valid:
                if self.creds.refresh_token:
                    self.creds.refresh(Request())
                    if self.save_token:
                        self.token_data = json.loads(self.creds.to_json())
                        self.save_token(self.token_data)
                else:
                    raise ValueError()
            self.email_service = build("gmail", "v1", credentials=self.creds, cache_discovery=False)
            self.calendar_service = build(
                "calendar", "v3", credentials=self.creds, cache_discovery=False
            )
        except Exception:
            raise SecurityError("Gmail authorization failed; reconnect Gmail.") from None

    def exchange_code_for_tokens(self, auth_code):
        flow = self._flow()
        try:
            flow.fetch_token(code=auth_code, timeout=self.settings.request_timeout)
            self.creds = flow.credentials
            token = json.loads(self.creds.to_json())
            if self.save_token:
                self.save_token(token)
            return token
        except Exception:
            raise SecurityError("Gmail authorization failed; reconnect Gmail.") from None

    @staticmethod
    def _plain_text(payload):
        """Read nested plain-text MIME parts without treating attachments as body text."""
        if payload.get("filename"):
            return None
        data = payload.get("body", {}).get("data")
        if payload.get("mimeType", "text/plain") == "text/plain" and data:
            headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
            content_type = Message()
            content_type["content-type"] = headers.get("content-type", "text/plain; charset=utf-8")
            try:
                decoded = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
                return decoded.decode(
                    content_type.get_content_charset() or "utf-8", errors="replace"
                )
            except (ValueError, LookupError):
                raise SecurityError("The email body could not be decoded.") from None
        for part in payload.get("parts", []):
            text = GmailTool._plain_text(part)
            if text is not None:
                return text
        return None

    def get_latest_email(self):
        """Read the newest returned unread message matching subject:slogan."""
        if self.email_service is None:
            self.authenticate_gmail()
        messages_api = self.email_service.users().messages()
        result = messages_api.list(userId="me", q="is:unread subject:slogan").execute()
        messages = [
            messages_api.get(userId="me", id=item["id"], format="full").execute()
            for item in result.get("messages", [])
        ]
        if not messages:
            return None
        latest = max(messages, key=lambda message: int(message.get("internalDate", 0)))
        payload = latest.get("payload", {})
        body = self._plain_text(payload)
        if body is None or not body.strip():
            raise SecurityError("The latest matching email has no readable plain-text body.")
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
        return {"subject": headers.get("subject", ""), "body": body, "sender": headers.get("from")}

    def schedule_post(self, title, description, start_time, end_time, time_zone="UTC"):
        """Create a new event in Google Calendar for a scheduled post."""
        if self.calendar_service is None:
            self.authenticate_gmail()

        event = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start_time, "timeZone": time_zone},
            "end": {"dateTime": end_time, "timeZone": time_zone},
        }

        event_result = (
            self.calendar_service.events().insert(calendarId="primary", body=event).execute()
        )
        logging.info("Calendar event created.")
        return event_result

    def delete_event(self, event_id):
        """Delete a Google Calendar event by its event ID."""
        if self.calendar_service is None:
            self.authenticate_gmail()  # Ensure the calendar service is authenticated

        try:
            self.calendar_service.events().delete(calendarId="primary", eventId=event_id).execute()
            logging.info(f"Google Calendar event {event_id} deleted successfully.")
        except HTTPError as e:
            if e.resp.status == 404:
                logging.info(f"Google Calendar event {event_id} already deleted or not found.")
            else:
                logging.error("Calendar event deletion failed.")
                raise
        except Exception:
            logging.error("Calendar event deletion failed.")
            raise

    def is_authenticated(self):
        # Presence only; provider validity is checked by authenticate_gmail on use.
        return bool(
            self.token_data
            and (self.token_data.get("refresh_token") or self.token_data.get("token"))
        )
