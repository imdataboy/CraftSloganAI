"""LinkedIn API client. No global account, token files, or swallowed errors."""

import time
from urllib.parse import urlencode, urlsplit

import requests

from ..security import SecurityError


class LinkedInError(RuntimeError):
    def __init__(self, operation, status_code=None, uncertain=False):
        self.operation = operation
        self.status_code = status_code
        self.uncertain = uncertain
        suffix = f" (HTTP {status_code})" if status_code else ""
        super().__init__(f"LinkedIn {operation} failed{suffix}.")


class LinkedInPoster:
    AUTHORIZATION_URL = "https://www.linkedin.com/oauth/v2/authorization"
    ACCESS_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
    POST_IMAGE_URL = "https://api.linkedin.com/v2/assets?action=registerUpload"
    POST_URL = "https://api.linkedin.com/v2/ugcPosts"

    def __init__(self, settings, token_data=None, http=None):
        self.settings = settings
        self.token_data = token_data or {}
        self.http = http or requests.Session()
        # Never obtain unrelated OS account credentials from .netrc.
        self.http.trust_env = False
        self.person_urn = None

    def _request(self, method, url, operation, accepted, publication=False, **kwargs):
        try:
            response = self.http.request(
                method, url, timeout=self.settings.request_timeout, allow_redirects=False, **kwargs
            )
        except (requests.Timeout, requests.ConnectionError):
            raise LinkedInError(operation, uncertain=publication) from None
        except requests.RequestException:
            raise LinkedInError(operation, uncertain=publication) from None
        if response.status_code not in accepted:
            raise LinkedInError(
                operation,
                response.status_code,
                uncertain=publication and response.status_code >= 500,
            )
        return response

    @staticmethod
    def _json(response, operation, uncertain=False):
        try:
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except (ValueError, TypeError):
            raise LinkedInError(operation, uncertain=uncertain) from None

    def get_auth_url(self, state):
        return (
            self.AUTHORIZATION_URL
            + "?"
            + urlencode(
                {
                    "response_type": "code",
                    "client_id": self.settings.provider_value("LINKEDIN_CLIENT_ID"),
                    "redirect_uri": self.settings.redirect_uri("linkedin"),
                    "scope": "openid profile w_member_social email",
                    "state": state,
                }
            )
        )

    def exchange_code_for_access_token(self, code):
        response = self._request(
            "POST",
            self.ACCESS_TOKEN_URL,
            "authorization",
            {200},
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.settings.redirect_uri("linkedin"),
                "client_id": self.settings.provider_value("LINKEDIN_CLIENT_ID"),
                "client_secret": self.settings.provider_value("LINKEDIN_CLIENT_SECRET"),
            },
        )
        data = self._json(response, "authorization")
        try:
            if not isinstance(data.get("access_token"), str) or not data["access_token"]:
                raise ValueError()
            lifetime = int(data["expires_in"])
            if lifetime <= 0:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise LinkedInError("authorization") from None
        data["expires_at"] = time.time() + lifetime
        self.token_data = data
        return data

    def get_access_token(self):
        if not self.is_authenticated():
            raise SecurityError("Reconnect LinkedIn; credentials are missing or expired.")
        return self.token_data["access_token"]

    def is_authenticated(self):
        try:
            return (
                bool(self.token_data.get("access_token"))
                and float(self.token_data.get("expires_at", 0)) > time.time()
            )
        except (ValueError, TypeError):
            return False

    def get_person_urn(self, token):
        response = self._request(
            "GET",
            "https://api.linkedin.com/v2/userinfo",
            "profile lookup",
            {200},
            headers={"Authorization": f"Bearer {token}"},
        )
        data = self._json(response, "profile lookup")
        if not isinstance(data.get("sub"), str) or not data["sub"]:
            raise LinkedInError("profile lookup")
        self.person_urn = f"urn:li:person:{data['sub']}"
        return self.person_urn

    def upload_image(self, token, image_bytes):
        if not isinstance(image_bytes, bytes):
            raise SecurityError("Only validated image bytes may be uploaded.")
        response = self._request(
            "POST",
            self.POST_IMAGE_URL,
            "image registration",
            {200},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "registerUploadRequest": {
                    "owner": self.person_urn,
                    "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                    "serviceRelationships": [
                        {"identifier": "urn:li:userGeneratedContent", "relationshipType": "OWNER"}
                    ],
                }
            },
        )
        data = self._json(response, "image registration")
        try:
            value = data["value"]
            url = value["uploadMechanism"][
                "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
            ]["uploadUrl"]
            asset = value["asset"]
            parsed = urlsplit(url)
            host = parsed.hostname or ""
            if (
                parsed.scheme != "https"
                or parsed.username
                or parsed.password
                or parsed.port not in (None, 443)
                or not (host == "linkedin.com" or host.endswith(".linkedin.com"))
                or not isinstance(asset, str)
            ):
                raise ValueError()
        except (KeyError, ValueError, TypeError):
            raise LinkedInError("image registration") from None
        self._request(
            "PUT",
            url,
            "image upload",
            {200, 201},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "image/png"},
            data=image_bytes,
        )
        return asset

    def post_content(self, token, text, asset=None):
        share = {
            "shareCommentary": {"text": text},
            "shareMediaCategory": "IMAGE" if asset else "NONE",
        }
        if asset:
            share["media"] = [{"status": "READY", "media": asset}]
        response = self._request(
            "POST",
            self.POST_URL,
            "publication",
            {201},
            publication=True,
            headers={
                "Authorization": f"Bearer {token}",
                "X-Restli-Protocol-Version": "2.0.0",
                "Content-Type": "application/json",
            },
            json={
                "author": self.person_urn,
                "lifecycleState": "PUBLISHED",
                "specificContent": {"com.linkedin.ugc.ShareContent": share},
                "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
            },
        )
        # 201 plus an identifier confirms creation; a malformed response is ambiguous.
        post_id = response.headers.get("X-RestLi-Id") or response.headers.get("x-restli-id")
        if not post_id:
            post_id = self._json(response, "publication", uncertain=True).get("id")
        if not isinstance(post_id, str) or not post_id:
            raise LinkedInError("publication confirmation", uncertain=True)
        return {"id": post_id}

    def post_to_linkedin(self, text, image_bytes=None):
        token = self.get_access_token()
        self.get_person_urn(token)
        asset = self.upload_image(token, image_bytes) if image_bytes is not None else None
        return self.post_content(token, text, asset)
