"""A small stand-in for the parts of GitHub's REST API that records.py uses, served on localhost for tests.

Contents (read a file or folder at a commit, write a file with the blob sha it replaces), commits/HEAD, and the two GitHub App
calls (find the installation on a repository, mint an installation token). Every write makes a new commit, and old commits stay
readable, so pinning a task to `records_commit` can be tested. Blob shas are git's own (sha1 of "blob <len>\\0<data>").
"""
from __future__ import annotations

import base64
import hashlib
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


class GitHubSim:
    def __init__(self):
        self.repos: dict[str, list[tuple[str, dict[str, bytes]]]] = {}    # repo -> [(commit, {path: bytes})], newest last
        self.tokens: dict[str, set[str]] = {}                             # token -> repos it can reach
        self.installations: dict[str, int] = {}                           # repo -> installation id
        self.app_jwts: list[str] = []                                     # JWTs the App presented, for the test to verify
        self.requests: list[tuple[str, str, dict]] = []                   # (method, path, headers) seen
        self._n = 0
        self._lock = threading.Lock()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()

    # ------------------------------------------------------------ test setup

    def add_repo(self, repo: str, files: dict[str, str], token: str | None = None, installation: int | None = None) -> str:
        commit = self._commit({p: t.encode() for p, t in files.items()})
        self.repos[repo] = [(commit, {p: t.encode() for p, t in files.items()})]
        if token:
            self.tokens.setdefault(token, set()).add(repo)
        if installation:
            self.installations[repo] = installation
        return commit

    def add_empty_repo(self, repo: str, token: str | None = None, installation: int | None = None) -> None:
        """A repository with no commit yet: GitHub answers 409 'Git Repository is empty.' to commits/HEAD and 404 to contents."""
        self.repos[repo] = []
        if token:
            self.tokens.setdefault(token, set()).add(repo)
        if installation:
            self.installations[repo] = installation

    def head(self, repo: str) -> str:
        return self.repos[repo][-1][0]

    def file(self, repo: str, path: str) -> str:
        return self.repos[repo][-1][1][path].decode()

    def _commit(self, files: dict[str, bytes]) -> str:
        self._n += 1
        return hashlib.sha1(f"commit {self._n}".encode() + json.dumps(sorted(files)).encode()).hexdigest()

    # ------------------------------------------------------------ HTTP

    def _handler(self):
        sim = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status, body, ctype="application/json"):
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _token(self):
                auth = self.headers.get("Authorization", "")
                return auth[7:] if auth.startswith("Bearer ") else ""

            def _route(self, method):
                u = urllib.parse.urlparse(self.path)
                q = dict(urllib.parse.parse_qsl(u.query))
                parts = [urllib.parse.unquote(p) for p in u.path.strip("/").split("/")]
                sim.requests.append((method, u.path, dict(self.headers)))
                token = self._token()
                if parts[:1] == ["app"] and method == "POST" and parts[1] == "installations" and parts[3] == "access_tokens":
                    sim.app_jwts.append(token)
                    inst = int(parts[2])
                    body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                    repos = [r for r, i in sim.installations.items() if i == inst and r.split("/")[1] in body.get("repositories", [])]
                    if not repos:
                        return self._send(422, {"message": "no such repository on the installation"})
                    tok = f"ghs_inst{inst}"
                    sim.tokens.setdefault(tok, set()).update(repos)
                    return self._send(201, {"token": tok, "expires_at": "2099-01-01T00:00:00Z", "permissions": body.get("permissions")})
                if parts[0] != "repos" or len(parts) < 4:
                    return self._send(404, {"message": "Not Found"})
                repo = f"{parts[1]}/{parts[2]}"
                if parts[3] == "installation":
                    sim.app_jwts.append(token)
                    if repo not in sim.installations:
                        return self._send(404, {"message": "Not Found"})
                    return self._send(200, {"id": sim.installations[repo]})
                if repo not in sim.repos or repo not in sim.tokens.get(token, set()):
                    return self._send(404 if token else 401, {"message": "Not Found"})
                history = sim.repos[repo]
                if parts[3] == "commits" and parts[4:] == ["HEAD"] and method == "GET":
                    if not history:
                        return self._send(409, {"message": "Git Repository is empty."})
                    return self._send(200, history[-1][0].encode(), "application/vnd.github.sha")
                if parts[3] != "contents":
                    return self._send(404, {"message": "Not Found"})
                path = "/".join(parts[4:])
                if not history and method == "GET":
                    return self._send(404, {"message": "This repository is empty."})
                if not history:
                    history.append((sim._commit({}), {}))        # the first PUT creates the first commit
                if method == "GET":
                    ref = q.get("ref") or history[-1][0]
                    snap = next((f for c, f in history if c == ref), None)
                    if snap is None:
                        return self._send(404, {"message": "No commit found for the ref"})
                    if path in snap:
                        data = snap[path]
                        return self._send(200, {"type": "file", "encoding": "base64", "path": path, "name": path.rsplit("/", 1)[-1],
                                                "sha": blob_sha(data), "size": len(data), "content": base64.encodebytes(data).decode()})
                    prefix = path + "/" if path else ""
                    names = {}
                    for p, data in snap.items():
                        if p.startswith(prefix):
                            rest = p[len(prefix):]
                            name = rest.split("/", 1)[0]
                            names[name] = ("dir", "", 0) if "/" in rest else ("file", blob_sha(data), len(data))
                    if not names:
                        return self._send(404, {"message": "Not Found"})
                    return self._send(200, [{"name": n, "path": prefix + n, "type": t, "sha": s, "size": z} for n, (t, s, z) in sorted(names.items())])
                if method == "PUT":
                    body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                    with sim._lock:
                        snap = dict(history[-1][1])
                        if path in snap and body.get("sha") != blob_sha(snap[path]):
                            return self._send(409 if body.get("sha") else 422, {"message": "sha does not match"})
                        if path not in snap and body.get("sha"):
                            return self._send(422, {"message": "sha given for a new file"})
                        created = path not in snap
                        snap[path] = base64.b64decode(body["content"])
                        commit = sim._commit(snap)
                        history.append((commit, snap))
                    return self._send(201 if created else 200, {"content": {"path": path, "sha": blob_sha(snap[path])}, "commit": {"sha": commit}})
                return self._send(405, {"message": "method"})

            def do_GET(self):
                self._route("GET")

            def do_PUT(self):
                self._route("PUT")

            def do_POST(self):
                self._route("POST")

        return H
