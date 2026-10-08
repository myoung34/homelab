"""Async client for Moonraker's native HTTP API.

Fluidd is a UI over Moonraker; the agent talks to Moonraker directly and
never scrapes Fluidd. Every call is bounded by a timeout and raises a typed
error so callers can report "unreachable" separately from "Klipper not ready"
separately from "Moonraker rejected the request".
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)


class MoonrakerError(Exception):
    """Base error for Moonraker calls."""


class MoonrakerUnreachableError(MoonrakerError):
    """Connection refused, DNS failure or timeout: Moonraker did not answer."""


class MoonrakerAPIError(MoonrakerError):
    def __init__(self, status: int, message: str, path: str) -> None:
        super().__init__(f"Moonraker {path} returned {status}: {message}")
        self.status = status
        self.message = message
        self.path = path

    @property
    def klippy_unavailable(self) -> bool:
        # Moonraker answers printer/* endpoints with 503 when Klippy is not
        # connected or not ready.
        return self.status == 503


class FileTooLargeError(MoonrakerError):
    pass


class MoonrakerClient:
    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        headers = {"X-Api-Key": api_key} if api_key else {}
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=httpx.Timeout(timeout),
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ core

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        raw_query: str | None = None,
        json: Any = None,
        files: Any = None,
        data: Any = None,
        timeout: float | None = None,
    ) -> Any:
        url = f"{path}?{raw_query}" if raw_query else path
        try:
            resp = await self._client.request(
                method,
                url,
                params=params,
                json=json,
                files=files,
                data=data,
                timeout=timeout if timeout is not None else httpx.USE_CLIENT_DEFAULT,
            )
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as err:
            raise MoonrakerUnreachableError(
                f"Moonraker at {self.base_url} unreachable ({type(err).__name__}: {err})"
            ) from err
        if resp.status_code >= 400:
            raise MoonrakerAPIError(resp.status_code, _error_message(resp), path)
        try:
            body = resp.json()
        except ValueError as err:
            raise MoonrakerAPIError(resp.status_code, "response was not JSON", path) from err
        if isinstance(body, dict) and "result" in body:
            return body["result"]
        if isinstance(body, dict) and "error" in body:
            err_obj = body["error"]
            code = int(err_obj.get("code", 500)) if isinstance(err_obj, dict) else 500
            msg = err_obj.get("message", str(err_obj)) if isinstance(err_obj, dict) else str(err_obj)
            raise MoonrakerAPIError(code, msg, path)
        return body

    # ------------------------------------------------------------ read APIs

    async def server_info(self) -> dict[str, Any]:
        return dict(await self._request("GET", "/server/info"))

    async def printer_info(self) -> dict[str, Any]:
        return dict(await self._request("GET", "/printer/info"))

    async def objects_list(self) -> list[str]:
        res = await self._request("GET", "/printer/objects/list")
        return list(res.get("objects", []))

    async def query_objects(self, objects: Mapping[str, Sequence[str] | None]) -> dict[str, Any]:
        """Query printer objects; returns {"eventtime": float, "status": {...}}."""
        parts = []
        for name, fields in objects.items():
            key = quote(name, safe="")
            parts.append(key if not fields else f"{key}={quote(','.join(fields), safe=',')}")
        return dict(await self._request("GET", "/printer/objects/query", raw_query="&".join(parts)))

    async def temperature_store(self) -> dict[str, Any]:
        return dict(await self._request("GET", "/server/temperature_store", params={"include_monitors": "false"}))

    async def gcode_store(self, count: int = 100) -> list[dict[str, Any]]:
        res = await self._request("GET", "/server/gcode_store", params={"count": count})
        return list(res.get("gcode_store", []))

    async def history_list(
        self,
        *,
        limit: int = 50,
        start: int = 0,
        since: float | None = None,
        before: float | None = None,
        order: str = "desc",
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "start": start, "order": order}
        if since is not None:
            params["since"] = since
        if before is not None:
            params["before"] = before
        res = await self._request("GET", "/server/history/list", params=params)
        return list(res.get("jobs", []))

    async def history_job(self, uid: str) -> dict[str, Any]:
        res = await self._request("GET", "/server/history/job", params={"uid": uid})
        return dict(res.get("job", {}))

    async def history_totals(self) -> dict[str, Any]:
        return dict(await self._request("GET", "/server/history/totals"))

    async def files_list(self, root: str = "gcodes") -> list[dict[str, Any]]:
        return list(await self._request("GET", "/server/files/list", params={"root": root}))

    async def file_metadata(self, filename: str) -> dict[str, Any]:
        return dict(await self._request("GET", "/server/files/metadata", params={"filename": filename}))

    async def directory(self, path: str) -> dict[str, Any]:
        return dict(await self._request("GET", "/server/files/directory", params={"path": path, "extended": "false"}))

    async def query_endstops(self) -> dict[str, str]:
        return dict(await self._request("GET", "/printer/query_endstops/status"))

    async def system_info(self) -> dict[str, Any]:
        return dict(await self._request("GET", "/machine/system_info"))

    async def proc_stats(self) -> dict[str, Any]:
        return dict(await self._request("GET", "/machine/proc_stats"))

    async def webcams_list(self) -> list[dict[str, Any]]:
        res = await self._request("GET", "/server/webcams/list")
        return list(res.get("webcams", []))

    async def download(self, root: str, path: str, *, max_bytes: int) -> bytes:
        """Download a file from a Moonraker root, refusing anything over max_bytes."""
        url = f"/server/files/{root}/{quote(path)}"
        try:
            async with self._client.stream("GET", url) as resp:
                if resp.status_code >= 400:
                    await resp.aread()
                    raise MoonrakerAPIError(resp.status_code, _error_message(resp), url)
                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise FileTooLargeError(f"{root}/{path} exceeds {max_bytes} bytes")
                    chunks.append(chunk)
                return b"".join(chunks)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as err:
            raise MoonrakerUnreachableError(f"Moonraker at {self.base_url} unreachable: {err}") from err

    async def download_tail(self, root: str, path: str, nbytes: int) -> tuple[bytes, bool]:
        """Return (last nbytes of the file, truncated?).

        Uses an HTTP suffix Range request; falls back to a capped full download
        if the server ignores Range.
        """
        url = f"/server/files/{root}/{quote(path)}"
        try:
            resp = await self._client.get(url, headers={"Range": f"bytes=-{nbytes}"})
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as err:
            raise MoonrakerUnreachableError(f"Moonraker at {self.base_url} unreachable: {err}") from err
        if resp.status_code == 206:
            total = _content_range_total(resp.headers.get("content-range"))
            return resp.content, total is None or total > len(resp.content)
        if resp.status_code >= 400:
            raise MoonrakerAPIError(resp.status_code, _error_message(resp), url)
        content = resp.content
        if len(content) > nbytes:
            return content[-nbytes:], True
        return content, False

    # ----------------------------------------------------------- write APIs
    # Only operations.py and remediation.py call these, after policy checks.

    async def gcode_script(self, script: str, *, timeout: float = 60.0) -> Any:
        return await self._request("POST", "/printer/gcode/script", params={"script": script}, timeout=timeout)

    async def print_start(self, filename: str) -> Any:
        return await self._request("POST", "/printer/print/start", params={"filename": filename})

    async def print_pause(self) -> Any:
        return await self._request("POST", "/printer/print/pause")

    async def print_resume(self) -> Any:
        return await self._request("POST", "/printer/print/resume")

    async def print_cancel(self) -> Any:
        return await self._request("POST", "/printer/print/cancel")

    async def restart(self) -> Any:
        return await self._request("POST", "/printer/restart")

    async def firmware_restart(self) -> Any:
        return await self._request("POST", "/printer/firmware_restart")

    async def emergency_stop(self) -> Any:
        return await self._request("POST", "/printer/emergency_stop")

    async def upload(self, root: str, path: str, content: bytes) -> Any:
        directory, _, filename = path.rpartition("/")
        data = {"root": root}
        if directory:
            data["path"] = directory
        return await self._request(
            "POST",
            "/server/files/upload",
            files={"file": (filename, content, "application/octet-stream")},
            data=data,
        )


def _error_message(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:300] or resp.reason_phrase
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        return str(body["error"].get("message", body["error"]))
    return str(body)[:300]


def _content_range_total(header: str | None) -> int | None:
    if not header or "/" not in header:
        return None
    total = header.rsplit("/", 1)[1]
    return int(total) if total.isdigit() else None


class Clock:
    """Injectable wall clock so tests can control staleness checks."""

    def now(self) -> float:
        return time.time()
