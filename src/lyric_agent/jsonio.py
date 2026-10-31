"""Shared JSON-file helpers for the small data/cache stores.

write_json_atomic uses mcp_channel's os.replace pattern so concurrent
readers (and a second process) never see a partially-written file.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def read_json(path: str | Path, default=None):
    """Parsed JSON at path, or `default` ({} if unset) on any failure."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {} if default is None else default


def write_json_atomic(path: str | Path, obj, indent: int = 1) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=indent)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def http_get_json(url: str, headers: dict | None = None,
                  timeout: int = 10, method: str = "GET"):
    """Fetch url and parse the body as JSON (shared fetcher: bilibili 搜索、
    例句词典等都走这里，UA/超时/错误策略只维护一处)。Raises on failure.
    method 可换成 "POST" 等(无请求体的简单情形)。"""
    import urllib.request

    req = urllib.request.Request(url, headers=headers or {}, method=method)
    opener = urllib.request.build_opener(V4FirstHTTPSHandler())
    with opener.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def create_connection_v4first(address, timeout=None, source_address=None):
    import socket

    host, port = address
    infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    infos.sort(key=lambda ai: ai[0] != socket.AF_INET)
    err = None
    for fam, typ, proto, _, addr in infos:
        sock = None
        try:
            sock = socket.socket(fam, typ, proto)
            if timeout is not None:
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(addr)
            return sock
        except OSError as exc:
            err = exc
            if sock is not None:
                sock.close()
    raise err if err else OSError(f"getaddrinfo returned nothing for {host}")


import http.client
import urllib.request as _urlreq


class _V4FirstHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = create_connection_v4first


class V4FirstHTTPSHandler(_urlreq.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_V4FirstHTTPSConnection, req,
                            context=self._context)
