"""Direct loading: read and write a person's career records in their own private GitHub repository.

Off unless CAREER_RECORDS is set. With it on, the checks in server.py can take file paths instead of document text, so the
model sends a path and this module fetches the file, and the records_* tools read, list and save files as plain text.

Two ways to reach a person's repository (CAREER_RECORDS):
  user_token  The gateway (Obot) signs each person in to GitHub and forwards that person's own token in a header
              (CAREER_RECORDS_TOKEN_HEADER, default x-github-token). The token can reach only what the person can, so the
              caller names the repository (`repo`, owner/name). Nothing is stored here.
  app         A GitHub App each person installs on only their career repository (Contents: read and write). This server holds
              the App's private key, knows the caller from the gateway's identity header (CAREER_RECORDS_USER_HEADER, default
              x-obot-user-id) and finds their repository in a small map file (CAREER_RECORDS_MAP: {"<user id>": "owner/repo"}).
              Needs CAREER_MCP_TOKEN, because the identity header can be trusted only when the gateway is the only caller.

Nothing is written to disk and file contents are never logged. App installation tokens are kept in memory until shortly
before they expire (at most one hour), keyed by repository.
"""
from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping

API = os.environ.get("CAREER_GITHUB_API", "https://api.github.com").rstrip("/")
USER_AGENT = "career-architect-records"
EXTENSIONS = (".md", ".yaml", ".yml", ".txt")
MAX_FILE = 250_000            # characters, the same limit as a document argument
MAX_FILES = 40
_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]*(/[A-Za-z0-9][A-Za-z0-9._ -]*){0,4}$")
_REPO = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$")
_REF = re.compile(r"^[A-Za-z0-9._/-]{1,100}$")


class RecordsError(Exception):
    """A message the caller can act on. Never contains file contents or a token."""


# ---------------------------------------------------------------- configuration

@dataclass(frozen=True)
class Config:
    mode: str = "off"                       # off | user_token | app
    token_header: str = "x-github-token"
    user_header: str = "x-obot-user-id"
    app_id: str = ""
    app_key: str = ""                       # PEM text
    repo_map: Mapping[str, str] | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "Config":
        mode = (env.get("CAREER_RECORDS") or "off").strip().lower()
        if mode not in ("off", "user_token", "app"):
            raise SystemExit(f"CAREER_RECORDS must be off, user_token or app, not {mode!r}")
        cfg = dict(mode=mode,
                   token_header=(env.get("CAREER_RECORDS_TOKEN_HEADER") or "x-github-token").strip().lower(),
                   user_header=(env.get("CAREER_RECORDS_USER_HEADER") or "x-obot-user-id").strip().lower())
        if mode == "app":
            missing = [k for k in ("CAREER_GITHUB_APP_ID", "CAREER_GITHUB_APP_KEY_FILE", "CAREER_RECORDS_MAP") if not env.get(k)]
            if missing:
                raise SystemExit(f"CAREER_RECORDS=app needs {', '.join(missing)}")
            with open(env["CAREER_GITHUB_APP_KEY_FILE"], encoding="utf-8") as f:
                cfg["app_key"] = f.read()
            with open(env["CAREER_RECORDS_MAP"], encoding="utf-8") as f:
                repo_map = json.load(f)
            if not isinstance(repo_map, dict) or not all(isinstance(v, str) and _REPO.match(v) for v in repo_map.values()):
                raise SystemExit("CAREER_RECORDS_MAP must be a JSON object of {\"<user id>\": \"owner/repo\"}")
            cfg.update(app_id=str(env["CAREER_GITHUB_APP_ID"]).strip(), repo_map=repo_map)
        return cls(**cfg)


# ---------------------------------------------------------------- validation

def check_path(path: Any, *, directory: bool = False) -> str:
    """A relative path inside the repository: no leading slash, no `..`, no dot-files, at most five levels, a text extension."""
    if not isinstance(path, str):
        raise RecordsError("a path must be text")
    p = path.strip()
    if directory:
        p = p.rstrip("/")
        if p == "":
            return ""
    if not _PATH.match(p) or ".." in p.split("/") or any(part.startswith(".") for part in p.split("/")):
        raise RecordsError(f"{path[:80]!r} is not a path this server reads (relative, no '..' or dot-files, at most five levels)")
    if not directory and not p.lower().endswith(EXTENSIONS):
        raise RecordsError(f"{p!r}: only {', '.join(EXTENSIONS)} files are records")
    return p


def check_repo(repo: Any) -> str:
    if not isinstance(repo, str) or not _REPO.match(repo.strip()):
        raise RecordsError("repo must be owner/name, for example jordan-lee/career-records")
    return repo.strip()


def check_ref(ref: Any) -> str:
    if ref in (None, ""):
        return ""
    if not isinstance(ref, str) or not _REF.match(ref) or ".." in ref:
        raise RecordsError("ref must be a commit id or branch name")
    return ref


# ---------------------------------------------------------------- HTTP

def _request(method: str, url: str, token: str, body: Any = None, accept: str = "application/vnd.github+json") -> tuple[int, bytes]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}", "Accept": accept, "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28", **({"Content-Type": "application/json"} if data else {})})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read(5_000_000)
    except urllib.error.HTTPError as e:
        return e.code, e.read(20_000)
    except (urllib.error.URLError, OSError) as e:
        raise RecordsError(f"GitHub could not be reached ({getattr(e, 'reason', e)})")


def _fail(status: int, what: str) -> RecordsError:
    if status in (401,):
        return RecordsError(f"{what}: GitHub refused the sign-in (expired or revoked). Sign in to GitHub again through the Jobs connector")
    if status == 403:
        return RecordsError(f"{what}: GitHub denied access (the token or App lacks Contents permission on this repository, or a rate limit)")
    if status == 404:
        return RecordsError(f"{what}: not found. Check the path, and that the repository exists and the Career Architect Records App is installed on it")
    if status in (409, 412):
        return RecordsError(f"{what}: the file changed since you read it. Read it again, merge, and show the person what differs before saving")
    if status == 422:
        return RecordsError(f"{what}: GitHub rejected the change (a file that exists needs the `sha` you read; a new file must not send one)")
    return RecordsError(f"{what}: GitHub answered {status}")


# ---------------------------------------------------------------- GitHub App tokens

def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def app_jwt(app_id: str, pem: str, now: float | None = None) -> str:
    """The short-lived JWT a GitHub App signs to ask for an installation token (RS256, ten minutes at most)."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    now = int(now if now is not None else time.time())
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claims = _b64url(json.dumps({"iat": now - 60, "exp": now + 540, "iss": app_id}).encode())
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    sig = key.sign(f"{header}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{header}.{claims}.{_b64url(sig)}"


class AppTokens:
    """Installation tokens per repository, limited to that one repository and to Contents. Kept in memory until five minutes before expiry."""

    def __init__(self, app_id: str, pem: str):
        self.app_id, self.pem = app_id, pem
        self._cache: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def token(self, repo: str) -> str:
        with self._lock:
            hit = self._cache.get(repo)
            if hit and hit[1] > time.time() + 300:
                return hit[0]
        jwt = app_jwt(self.app_id, self.pem)
        status, body = _request("GET", f"{API}/repos/{repo}/installation", jwt)
        if status != 200:
            raise _fail(status, f"the Career Architect Records App on {repo}")
        inst = json.loads(body)["id"]
        status, body = _request("POST", f"{API}/app/installations/{inst}/access_tokens", jwt,
                                {"repositories": [repo.split("/", 1)[1]], "permissions": {"contents": "write"}})
        if status != 201:
            raise _fail(status, f"a token for {repo}")
        got = json.loads(body)
        expires = time.time() + 3000
        try:
            expires = time.mktime(time.strptime(got["expires_at"], "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
        except (KeyError, ValueError):
            pass
        with self._lock:
            self._cache[repo] = (got["token"], expires)
        return got["token"]


# ---------------------------------------------------------------- the store

class Repo:
    """One person's records repository, reached with a token that can see it."""

    def __init__(self, repo: str, token: str):
        self.repo, self.token = repo, token
        self.empty = False          # set by head(): a repository with no commit yet (GitHub answers 409 "empty")

    def _url(self, *parts: str, **query: str) -> str:
        path = "/".join(urllib.parse.quote(p, safe="/") for p in parts)
        q = urllib.parse.urlencode({k: v for k, v in query.items() if v})
        return f"{API}/repos/{self.repo}/{path}" + (f"?{q}" if q else "")

    def head(self) -> str:
        """The commit the default branch points at now. Reads in one task pin to it so every check sees the same version."""
        status, body = _request("GET", self._url("commits", "HEAD"), self.token, accept="application/vnd.github.sha")
        if status == 409 and b"empty" in body.lower():
            # A new repository has no commit, so there is nothing to pin yet: an empty `ref` reads the default branch. The first
            # records_write creates the first commit.
            self.empty = True
            return ""
        if status != 200:
            raise _fail(status, f"the repository {self.repo}")
        return body.decode().strip()

    def list(self, directory: str, ref: str) -> list[dict]:
        directory = check_path(directory, directory=True)
        if self.empty:
            return []
        status, body = _request("GET", self._url("contents", directory, ref=ref) if directory else self._url("contents", ref=ref), self.token)
        if status != 200:
            raise _fail(status, f"the folder {directory or '/'}")
        items = json.loads(body)
        if not isinstance(items, list):
            raise RecordsError(f"{directory} is a file, not a folder")
        return [{"path": i["path"], "type": "folder" if i["type"] == "dir" else "file", "sha": i.get("sha", ""), "size": i.get("size", 0)}
                for i in items if not i["name"].startswith(".")]

    def read(self, path: str, ref: str) -> dict:
        path = check_path(path)
        if self.empty:
            raise RecordsError(f"{path}: not found. The repository has no files yet")
        status, body = _request("GET", self._url("contents", path, ref=ref), self.token)
        if status != 200:
            raise _fail(status, path)
        item = json.loads(body)
        if not isinstance(item, dict) or item.get("type") != "file" or item.get("encoding") != "base64":
            raise RecordsError(f"{path} is not a text file this server can read")
        text = base64.b64decode(item["content"]).decode("utf-8")
        if len(text) > MAX_FILE:
            raise RecordsError(f"{path} is {len(text):,} characters; the limit is {MAX_FILE:,}")
        return {"path": path, "text": text, "sha": item["sha"]}

    def read_many(self, paths: list[str], ref: str) -> list[dict]:
        """Files, and every record file directly inside a path that ends with '/', in order."""
        if len(paths) > MAX_FILES:
            raise RecordsError(f"at most {MAX_FILES} paths in one call")
        out: list[dict] = []
        for p in paths:
            if isinstance(p, str) and p.strip().endswith("/"):
                files = [i["path"] for i in self.list(p, ref) if i["type"] == "file" and i["path"].lower().endswith(EXTENSIONS)]
                if not files:
                    raise RecordsError(f"{p} has no record files")
                out += [self.read(f, ref) for f in sorted(files)]
            else:
                out.append(self.read(p, ref))
            if len(out) > MAX_FILES:
                raise RecordsError(f"more than {MAX_FILES} files; name the ones this call needs")
        return out

    def write(self, path: str, text: str, sha: str, message: str) -> dict:
        path = check_path(path)
        if not isinstance(text, str) or len(text) > MAX_FILE:
            raise RecordsError(f"text must be at most {MAX_FILE:,} characters")
        body: dict[str, Any] = {"message": (message or f"Update {path}")[:200], "content": base64.b64encode(text.encode()).decode()}
        if sha:
            body["sha"] = sha
        status, resp = _request("PUT", self._url("contents", path), self.token, body)
        if status not in (200, 201):
            raise _fail(status, path)
        got = json.loads(resp)
        return {"path": path, "sha": got["content"]["sha"], "commit": got["commit"]["sha"], "created": status == 201}


# ---------------------------------------------------------------- per request

class Records:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.app = AppTokens(cfg.app_id, cfg.app_key) if cfg.mode == "app" else None

    @property
    def enabled(self) -> bool:
        return self.cfg.mode != "off"

    def open(self, headers: Mapping[str, str] | None, repo: str | None) -> Repo:
        """The caller's repository. In user_token mode the caller's own token decides what it can reach; in app mode the
        gateway's identity header picks the one repository mapped to that person, and a different `repo` is refused."""
        if not self.enabled:
            raise RecordsError("direct loading is not enabled on this server: pass document text instead (references/storage.md)")
        h = {k.lower(): v for k, v in (headers or {}).items()}
        if self.cfg.mode == "user_token":
            raw = (h.get(self.cfg.token_header) or "").strip()
            token = raw[7:].strip() if raw[:7].lower() == "bearer " else raw
            if not token:
                raise RecordsError("no GitHub sign-in reached the server. Connect GitHub in the Jobs connector, or use Drive")
            if not repo:
                raise RecordsError("repo is required: the person's records repository, owner/name, from their profile")
            return Repo(check_repo(repo), token)
        user = (h.get(self.cfg.user_header) or "").strip()
        mapped = (self.cfg.repo_map or {}).get(user) if user else None
        if not mapped:
            raise RecordsError("no records repository is set up for this account. The administrator adds it (docs/OPERATIONS.md, 'Records on GitHub')")
        if repo and check_repo(repo).lower() != mapped.lower():
            raise RecordsError("that repository is not the one set up for this account")
        return Repo(mapped, self.app.token(mapped))

    def status(self, headers: Mapping[str, str] | None, repo: str | None) -> dict:
        """What the gateway sent (header names only, never values, except the caller's own user id) and whether the repository answers."""
        h = {k.lower(): v for k, v in (headers or {}).items()}
        out: dict[str, Any] = {
            "mode": self.cfg.mode,
            "headers_seen": sorted(k for k in h if k.startswith("x-obot") or k in ("authorization", self.cfg.token_header)),
            "token_header": self.cfg.token_header if self.cfg.mode == "user_token" else None,
            "token_header_present": bool(h.get(self.cfg.token_header)) if self.cfg.mode == "user_token" else None,
            "user_id": h.get(self.cfg.user_header) or None,
        }
        if not self.enabled:
            out["reachable"] = False
            return out
        try:
            r = self.open(headers, repo)
            commit = r.head()
            out.update(repo=r.repo, reachable=True, commit=commit)
            if r.empty:
                out["empty"] = True     # no commit yet: fine, the first records_write creates it
        except RecordsError as e:
            out.update(reachable=False, problem=str(e))
        return out
