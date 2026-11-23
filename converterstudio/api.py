"""The Converter Studio REST API (v1), as this package uses it, with urllib only.

Used only for a cloud conversion the user picked, and for "Show Plan and Credits". Every request
carries the account's API key, except the upload and download requests: their addresses carry
their own short-lived tokens. The key is sent only to the API's own address and never appears in
a message or a log.

See https://converter.studio/developers.
"""

import json
import os
import platform
import socket
import ssl
import time
import urllib.error
import urllib.request
from urllib.parse import quote, urlsplit

from . import API_KEY_ENV, CLIENT, DEFAULT_BASE_URL, VERSION

CLIENT_HEADER = "X-Converter-Studio-Client"

# Bytes in one upload request. The API takes parts of up to 95 MB, in order, with an
# Upload-Offset header; smaller parts show progress sooner.
PART_BYTES = 8 * 1024 * 1024

# Seconds for an ordinary request; a long poll adds its own wait.
TIMEOUT = 30

# Statuses after which a conversion changes no more (`quoted` waits for the user's go-ahead).
FINAL = ("done", "failed", "expired", "canceled")

# Our own error codes (the API's come from its answers).
NETWORK = "network"
TLS = "tls"
BAD_RESPONSE = "badResponse"
UNEXPECTED_URL = "unexpectedUrl"
NO_KEY = "noKey"
INSECURE_URL = "insecureUrl"

LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


class ApiError(Exception):
    """A request that did not work. `message` is the API's own sentence when it sent one."""

    def __init__(self, status, code, message="", params=None):
        super().__init__(message or code)
        self.status = status
        self.code = code
        self.message = message or ""
        self.params = params or {}

    @classmethod
    def from_body(cls, status, body):
        """The API's `{ "error": { "code", "message", "params" } }`, or a generic error."""
        try:
            data = json.loads(body.decode("utf-8")) if body else {}
        except (ValueError, UnicodeDecodeError):
            data = {}
        error = data.get("error") if isinstance(data, dict) else None
        if isinstance(error, dict) and isinstance(error.get("code"), str):
            params = error.get("params") if isinstance(error.get("params"), dict) else {}
            return cls(status, error["code"], str(error.get("message") or ""), params)
        if status == 401:
            return cls(status, "invalidApiKey")
        if status == 402:
            return cls(status, "notEnoughCredits")
        return cls(status, BAD_RESPONSE if status < 500 else "serverBusy")

    @classmethod
    def from_view(cls, view):
        """The error of a conversion that failed or expired."""
        error = view.get("error") or {}
        code = error.get("code") or ("fileExpired" if view.get("status") == "expired" else "conversionFailed")
        return cls(200, code, str(error.get("message") or ""), error.get("params") or {})


class Canceled(Exception):
    """The user stopped it."""


def api_key(settings, env=None):
    """The API key: the setting `api_key`, or else the environment variable."""
    env = os.environ if env is None else env
    key = str(settings.get("api_key") or "").strip()
    return key or str(env.get(API_KEY_ENV) or "").strip()


def base_url(settings):
    """The API's address from the settings, checked: https, or http only on this computer."""
    url = str(settings.get("api_url") or DEFAULT_BASE_URL).strip().rstrip("/")
    try:
        parts = urlsplit(url)
    except ValueError:
        raise ApiError(0, INSECURE_URL)
    host = (parts.hostname or "").lower()
    if parts.scheme == "https" and host:
        return url
    if parts.scheme == "http" and host in LOCAL_HOSTS:
        return url
    raise ApiError(0, INSECURE_URL)


def user_agent(editor_version=""):
    editor = " SublimeText/" + editor_version if editor_version else ""
    return "ConverterStudio-Sublime/%s%s (%s)" % (VERSION, editor, platform.system() or "unknown")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Redirects are not followed: an answer that moves elsewhere is not the API's."""

    def redirect_request(self, *args, **kwargs):
        return None


class Response:
    """What a transport returns: status, lower-case headers, and the body to read."""

    def __init__(self, status, headers, stream):
        self.status = status
        self.headers = headers
        self._stream = stream

    def read(self, size=None):
        # read() with no count, never read(-1): Python 3.8's http.client refuses -1.
        if self._stream is None:
            return b""
        if size is None or size < 0:
            return self._stream.read()
        return self._stream.read(size)

    def close(self):
        if self._stream is not None:
            try:
                self._stream.close()
            except Exception:  # noqa: BLE001, S110 (closing a finished answer)
                pass


def urllib_transport(context=None):
    """Sends requests with urllib (the system's proxy settings apply); never follows redirects."""
    opener = urllib.request.build_opener(_NoRedirect(), urllib.request.HTTPSHandler(context=context))

    def send(method, url, headers, body, timeout):
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            raw = opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            return Response(error.code, {k.lower(): v for k, v in error.headers.items()}, error)
        except urllib.error.URLError as error:
            if isinstance(getattr(error, "reason", None), ssl.SSLCertVerificationError):
                raise ApiError(0, TLS)
            raise ApiError(0, NETWORK)
        except ssl.SSLCertVerificationError:
            raise ApiError(0, TLS)
        except (OSError, socket.timeout, ValueError):
            raise ApiError(0, NETWORK)
        return Response(raw.status, {k.lower(): v for k, v in raw.headers.items()}, raw)

    return send


def _retry_after(response, attempt):
    try:
        seconds = float(response.headers.get("retry-after", ""))
    except (TypeError, ValueError, AttributeError):
        seconds = 2.0**attempt
    return max(0.5, min(30.0, seconds))


class Client:
    """The API with one account's key."""

    def __init__(self, base, key, transport, editor_version="", sleep=time.sleep, attempts=4):
        self.base = base.rstrip("/")
        self.key = key
        self.transport = transport
        self.user_agent = user_agent(editor_version)
        self.sleep = sleep
        self.attempts = attempts

    def _headers(self, with_key):
        headers = {
            "Accept": "application/json",
            "User-Agent": self.user_agent,
            CLIENT_HEADER: "%s/%s" % (CLIENT, VERSION),
        }
        if with_key:
            headers["Authorization"] = "Bearer " + self.key
        return headers

    def _send(self, method, url, headers, body, timeout):
        """One request, tried again after a network error, 429 or 502–504."""
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self.transport(method, url, headers, body, timeout)
            except ApiError as error:
                if error.code != NETWORK or attempt >= self.attempts:
                    raise
                self.sleep(min(30.0, 2.0 ** (attempt - 1)))
                continue
            if response.status in (429, 502, 503, 504) and attempt < self.attempts:
                wait = _retry_after(response, attempt - 1)
                response.close()
                self.sleep(wait)
                continue
            return response

    def call(self, method, path, payload=None, extra_headers=None, timeout=TIMEOUT, with_key=True):
        """A JSON request; the answer's JSON object, or ApiError."""
        if with_key and not self.key:
            raise ApiError(401, NO_KEY)
        headers = self._headers(with_key)
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if extra_headers:
            headers.update(extra_headers)
        response = self._send(method, self.base + path, headers, body, timeout)
        try:
            raw = response.read()
        except (OSError, socket.timeout, ValueError):
            raise ApiError(0, NETWORK)
        finally:
            response.close()
        if response.status >= 400 or response.status < 200:
            raise ApiError.from_body(response.status, raw)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ApiError(response.status, BAD_RESPONSE)
        if not isinstance(data, dict):
            raise ApiError(response.status, BAD_RESPONSE)
        return data

    # -- the API ----------------------------------------------------------------------------

    def formats(self):
        """Every format and what it can become (no key needed)."""
        return self.call("GET", "/v1/formats", with_key=False).get("formats") or []

    def account(self):
        """The key's account: plan, credits, allowance."""
        return self.call("GET", "/v1/account")

    def create_upload(self, name, size):
        """A slot to send one file to: {id, uploadUrl, partBytes, maxBytes, …}."""
        return self.call("POST", "/v1/uploads", {"fileName": name, "size": size})

    def send_file(self, upload, path, size, progress=None, cancelled=None):
        """Sends a local file to its upload slot in parts, each with its Upload-Offset."""
        url = upload.get("uploadUrl") or ""
        if not self.same_origin(url):
            raise ApiError(0, UNEXPECTED_URL)
        part = max(1, min(PART_BYTES, int(upload.get("partBytes") or PART_BYTES)))
        offset = 0
        if progress:
            progress(0, size)
        with open(path, "rb") as handle:
            while offset < size:
                if cancelled and cancelled():
                    raise Canceled()
                handle.seek(offset)
                chunk = handle.read(min(part, size - offset))
                if not chunk:
                    raise ApiError(0, "fileChanged")
                headers = self._headers(False)
                headers.update({"Content-Type": "application/octet-stream", "Upload-Offset": str(offset)})
                response = self._send("PUT", url, headers, chunk, TIMEOUT + 60)
                try:
                    raw = response.read()
                finally:
                    response.close()
                if response.status == 409:
                    error = ApiError.from_body(409, raw)
                    received = error.params.get("received")
                    if isinstance(received, (int, float)) and int(received) != offset and 0 <= int(received) <= size:
                        # The API holds a different amount (a part broke off): go on from there.
                        offset = int(received)
                        continue
                    raise error
                if response.status >= 400:
                    raise ApiError.from_body(response.status, raw)
                offset += len(chunk)
                if progress:
                    progress(offset, size)

    def convert(self, upload_id, to, max_credits, idempotency_key, options=None):
        """Starts converting an uploaded file; the same Idempotency-Key makes a retry harmless."""
        body = {"uploadId": upload_id, "to": to, "maxCredits": max_credits}
        if options:
            body["options"] = options
        return self.call("POST", "/v1/conversions", body, {"Idempotency-Key": idempotency_key})

    def conversion(self, conversion_id, wait=0):
        """A conversion's state, waiting up to `wait` seconds (at most 60) for it to settle."""
        wait = max(0, min(60, int(wait)))
        path = "/v1/conversions/" + quote(conversion_id, safe="") + ("?wait=%d" % wait if wait else "")
        return self.call("GET", path, timeout=TIMEOUT + wait)

    def confirm(self, conversion_id):
        """Goes ahead with a conversion that costs more than it was allowed."""
        return self.call("POST", "/v1/conversions/" + quote(conversion_id, safe="") + "/confirm", {})

    def download(self, url, destination, progress=None, cancelled=None):
        """Saves a result to a local file; returns its size."""
        if not self.same_origin(url):
            raise ApiError(0, UNEXPECTED_URL)
        response = self._send("GET", url, self._headers(False), None, TIMEOUT + 60)
        try:
            if response.status >= 400 or response.status < 200:
                raise ApiError.from_body(response.status, response.read())
            try:
                total = int(response.headers.get("content-length") or 0)
            except ValueError:
                total = 0
            done = 0
            try:
                with open(destination, "wb") as out:
                    while True:
                        if cancelled and cancelled():
                            raise Canceled()
                        chunk = response.read(256 * 1024)
                        if not chunk:
                            break
                        done += len(chunk)
                        out.write(chunk)
                        if progress:
                            progress(done, total)
            except BaseException as error:
                _remove(destination)
                if isinstance(error, (OSError, ValueError)):
                    raise ApiError(0, NETWORK)
                raise
            if total and done != total:
                _remove(destination)
                raise ApiError(0, NETWORK)
            return done
        finally:
            response.close()

    def same_origin(self, url):
        """Whether an address is on the API's own scheme, host and port."""
        try:
            a, b = urlsplit(self.base), urlsplit(url)
            return (a.scheme, (a.hostname or "").lower(), a.port) == (b.scheme, (b.hostname or "").lower(), b.port)
        except ValueError:
            return False


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass
