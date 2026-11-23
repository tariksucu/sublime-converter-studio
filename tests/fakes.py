"""A fake Converter Studio API behind the client's transport interface."""

import io
import json

from converterstudio import api

BASE = "https://converter.example/api"
KEY = "cvs_live_test_key_123"


class FakeApi:
    """Answers like the API does; records every request."""

    def __init__(self, base=BASE, key=KEY):
        self.base = base
        self.key = key
        self.requests = []
        self.uploads = {}
        self.statuses = []  # what successive GET /v1/conversions/:id return
        self.output_name = "photo.jpg"
        self.price = 1
        self.quoted = False
        self.fail_with = None
        self.queue = []  # (status, headers, body) answers that come first, for any request
        self.confirmed = False

    def __call__(self, method, url, headers, body, timeout):
        self.requests.append({"method": method, "url": url, "headers": dict(headers), "body": body})
        if self.queue:
            status, extra, payload = self.queue.pop(0)
            if isinstance(payload, Exception):
                raise payload
            return self._answer(status, payload, extra)
        path = url[len(self.base) :] if url.startswith(self.base) else url
        if path.startswith("/v1/") and not path.startswith("/v1/uploads/") and path != "/v1/formats":
            if headers.get("Authorization") != "Bearer " + self.key:
                return self._answer(401, {"error": {"code": "invalidApiKey", "message": "This API key does not work."}})
        if method == "GET" and path == "/v1/formats":
            return self._answer(200, {"formats": [{"id": "jpg"}]})
        if method == "GET" and path == "/v1/account":
            return self._answer(200, {"email": "a@example.com", "plan": "pro", "credits": 99})
        if method == "POST" and path == "/v1/uploads":
            data = json.loads(body)
            self.uploads["up_1"] = {"name": data["fileName"], "size": data["size"], "data": b""}
            return self._answer(
                201,
                {"id": "up_1", "uploadUrl": self.base + "/v1/uploads/up_1?token=t", "partBytes": 4, "maxBytes": 10**9},
            )
        if method == "PUT" and path.startswith("/v1/uploads/up_1"):
            upload = self.uploads["up_1"]
            offset = int(headers.get("Upload-Offset", "0"))
            if offset != len(upload["data"]):
                return self._answer(
                    409, {"error": {"code": "uploadOffset", "params": {"received": len(upload["data"])}}}
                )
            upload["data"] += body
            return self._answer(200, {"id": "up_1", "status": "partial", "received": len(upload["data"])})
        if method == "POST" and path == "/v1/conversions":
            if self.fail_with:
                return self._answer(*self.fail_with)
            data = json.loads(body)
            self.started = data
            status = "quoted" if self.quoted else "queued"
            return self._answer(201, self.view(status))
        if method == "POST" and path == "/v1/conversions/cv_1/confirm":
            self.confirmed = True
            return self._answer(200, self.view("processing"))
        if method == "GET" and path.startswith("/v1/conversions/cv_1"):
            status = self.statuses.pop(0) if self.statuses else "done"
            return self._answer(200, self.view(status))
        if method == "GET" and path.startswith("/jobs/cv_1/download"):
            return self._answer(200, b"JPEGDATA", {"content-length": "8"})
        return self._answer(404, {"error": {"code": "notFound", "message": "Not found."}})

    def view(self, status):
        view = {
            "id": "cv_1",
            "status": status,
            "progress": 50 if status == "processing" else 0,
            "credits": self.price,
            "outputName": self.output_name,
            "downloadUrl": self.base + "/jobs/cv_1/download?token=d" if status == "done" else None,
            "error": None,
        }
        if status == "failed":
            view["error"] = {"code": "conversionFailed", "message": "This file could not be converted."}
        return view

    def _answer(self, status, payload, headers=None):
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        return api.Response(status, dict(headers or {}), io.BytesIO(raw))


def client(fake=None, key=KEY, sleep=None):
    fake = fake or FakeApi()
    return api.Client(BASE, key, fake, "4215", sleep=sleep or (lambda s: None)), fake
