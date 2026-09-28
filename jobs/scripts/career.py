#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = ["pyyaml"]
# ///
"""Deterministic helpers for the jobs skill.

Everything that does not need judgment lives here so the model spends tokens
only on requirement extraction and bullet wording:

  init      copy the profile/facts templates into the data folder
  skills    validate facts.md and regenerate skills.md (years = union of role spans)
  match     coverage table + score ceiling for a list of job requirements
  select    ranked candidate atoms per role for a list of tags
  build     lint a selection.yml and render resume.md for review
  push      duplicate the Reactive Resume master, patch in the selection, save the PDF
  pdf       download a resume (or cover letter) PDF from Reactive Resume
  resumes   list Reactive Resume resumes (finds the master id, tests the key)
  cover     lint cover.yml, create or update the job's letter in Reactive Resume > Cover Letters, fill the resume's
            cover-letter section, save cover.pdf
  letters   the saved Cover Letters list: ls | show | export | import | rename | duplicate | refresh-style | delete
  master    find your Master resume in Reactive Resume and record its id in profile.md
  posting   read a public Ashby/Greenhouse/Lever posting: pay range, reports-to, description
  apply     application tracker in Reactive Resume: add (updates an existing row) | set | find | show | ls | stats | doc
  check     self-test the Reactive Resume connection: URL, reachability, API key, master resume, cover letters API

Data folder: --data, $CAREER_DATA, or the default below.
Reactive Resume URL: rr_url in profile.md (one place; $RR_URL overrides). API key: $RR_API_KEY or
~/.config/career/rr.env. The key is never stored in the data folder.
"""
from __future__ import annotations

import argparse
import base64
import copy
import datetime as dt
import hashlib
import html
import ipaddress
import json
import os
import re
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import yaml

DEFAULT_ROOT = Path.home() / "Documents/Career Architect"
CONF = Path.home() / ".config/career/rr.env"
ASSETS = Path(__file__).resolve().parent.parent / "assets"

DEPTH = {"exposure": 0, "used": 1, "owned": 2, "designed": 3}
STATUS = {"verified", "needs_number", "unconfirmed", "excluded"}
USABLE = {"verified", "needs_number"}
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def die(msg: str, code: int = 2):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------- loading

class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that refuses YAML aliases. The hosted service parses text written by other people, and a chain of
    aliases ("billion laughs") expands to gigabytes; nothing in a facts or profile document needs one."""

    def compose_node(self, parent, index):
        if self.check_event(yaml.events.AliasEvent):
            raise yaml.YAMLError("YAML aliases (&anchor and *alias) are not allowed in career documents")
        return super().compose_node(parent, index)


def load_yaml(text: str):
    return yaml.load(text, Loader=_StrictLoader)


def parse_block(text: str) -> dict:
    """Parse the first ```yaml fence of a markdown document (or the whole text)."""
    m = re.search(r"```ya?ml\n(.*?)```", text, re.S)
    return load_yaml(m.group(1) if m else text) or {}


def parse_front(text: str) -> dict:
    """Parse the YAML front matter of a markdown document."""
    m = re.match(r"---\n(.*?)\n---", text, re.S)
    return (load_yaml(m.group(1)) if m else {}) or {}


def read_block(path: Path) -> dict:
    return parse_block(path.read_text())


def read_front(path: Path) -> dict:
    return parse_front(path.read_text())


# ---------------------------------------------------------------- documents stored in Google Drive

# Where the text comes from decides what was done to it, so `source` names the reader:
#   docs        `get_document` of the Google Docs server: markdown converted from the document body. Nothing is escaped, but the
#               body always opens with a section break, which the converter renders as a leading "---" line.
#   drive_read  a Drive connector that converts a Doc itself (Claude's own `read_file_content`): every line followed by a blank
#               line, a blank line as two spaces, markdown punctuation backslash-escaped.
#   base64      a Drive export, base64 encoded, with a byte order mark and CRLF line ends.
#   plain       already clean.
# `auto` recognises each by its own marks and otherwise leaves the text alone: guessing wrong would change the person's facts.
_MD_ESCAPED = re.compile(r"\\([\\`*_{}\[\]()#+\-.!>~|<])")
_DOCS_BREAK = re.compile(r"[ \t]*---[ \t]*(?:\n|\Z)")


def _looks_doubled(t: str) -> bool:
    """The shape of `drive_read` output. The shape alone (a blank line after every line) also describes ordinary prose whose
    paragraphs are separated by blank lines, so it counts only with one of the connector's own marks: a blank original line
    written as two spaces, or backslash-escaped punctuation."""
    lines = t.replace("\r\n", "\n").split("\n")
    if not (len(lines) >= 3 and len(lines) % 2 == 1 and all(x == "" for x in lines[1::2]) and any(x.strip() for x in lines[0::2])):
        return False
    return any(x == "  " for x in lines[0::2]) or bool(_MD_ESCAPED.search(t))


def _drop_docs_break(t: str) -> str:
    """Remove the section-break line the Docs converter puts first (the text may also have lost its leading newline)."""
    m = _DOCS_BREAK.match(t.lstrip("\n"))
    return t.lstrip("\n")[m.end():] if m else t


def normalize_drive_text(text: str, source: str = "auto") -> str:
    """Restore the original text of a document that was stored in Google Drive as a Google Doc, whichever way it was read
    (see the table above). 'auto' picks by each shape's own marks and falls back to plain."""
    if source not in ("auto", "docs", "drive_read", "base64", "plain"):
        raise ValueError("source must be auto, docs, drive_read, base64 or plain")
    t = text

    def decode(s: str) -> str:
        return base64.b64decode("".join(s.split()), validate=True).decode("utf-8")

    if source == "auto":
        squashed = "".join(t.split())
        if t.startswith(("\n---\n", "---\n---\n")):
            source = "docs"                 # a section break followed by the document's own text (which may open with `---`)
        elif len(squashed) >= 16 and len(squashed) % 4 == 0 and re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", squashed):
            try:
                t, source = decode(t), "plain"
            except (ValueError, UnicodeDecodeError):
                source = "plain"            # ordinary words that happen to look like base64
        else:
            source = "drive_read" if _looks_doubled(t) else "plain"
    elif source == "base64":
        try:
            t, source = decode(t), "plain"
        except (ValueError, UnicodeDecodeError) as e:
            raise ValueError(f"not valid base64 text: {e}")
    t = t.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if source == "docs":
        t = _drop_docs_break(t)
    elif source == "drive_read":
        t = "\n".join("" if piece == "  " else piece for piece in t.split("\n\n"))
        t = _MD_ESCAPED.sub(r"\1", t)
    return t


def merge_facts(docs) -> dict:
    """One facts dict from several fragments: the layout kept in Drive is a shared document (aliases, credentials, education)
    plus one document per role, each a valid slice of the usual facts YAML. Lists are concatenated and alias lists are
    unioned. A role or atom id that occurs twice is reported by `validate`, not silently merged."""
    out: dict = {"aliases": {}, "credentials": [], "education": [], "roles": [], "log": []}
    for doc in docs:
        d = parse_block(doc) if isinstance(doc, str) else (doc or {})
        if not isinstance(d, dict):
            raise ValueError("a facts document must be a YAML mapping (aliases, credentials, education, roles, log)")
        for key, val in d.items():
            if key == "aliases":
                for tag, syns in (val or {}).items():
                    have = out["aliases"].setdefault(tag, [])
                    have += [s for s in (syns or []) if s not in have]
            elif key in ("credentials", "education", "roles", "log"):
                out[key] += val or []
            else:
                out.setdefault(key, val)
    return out


class Ctx:
    def __init__(self, root: str | None, today: dt.date):
        self.root = Path(root or os.environ.get("CAREER_DATA") or DEFAULT_ROOT).expanduser()
        self.today = today
        self._facts = None
        self._profile = None

    @classmethod
    def from_data(cls, facts: dict, profile: dict, today: dt.date) -> "Ctx":
        """A context over documents already in memory (the hosted service). It never touches a file."""
        ctx = cls("/nonexistent/career-data", today)
        ctx._facts, ctx._profile = facts, profile
        return ctx

    @property
    def facts(self) -> dict:
        if self._facts is None:
            p = self.root / "facts.md"
            if not p.exists():
                die(f"{p} not found. Run `career init` first.")
            self._facts = read_block(p)
        return self._facts

    @property
    def profile(self) -> dict:
        if self._profile is None:
            p = self.root / "profile.md"
            self._profile = read_front(p) if p.exists() else {}
        return self._profile

    def job_dir(self, arg: str) -> Path:
        p = Path(arg).expanduser()
        if p.is_file():
            return p.parent
        if p.is_dir():
            return p
        return self.root / "jobs" / arg


# ---------------------------------------------------------------- tags & dates

def norm(s) -> str:
    return re.sub(r"[^a-z0-9+#]+", "-", str(s).lower()).strip("-")


def alias_map(facts: dict) -> dict:
    m = {}
    for canon, syns in (facts.get("aliases") or {}).items():
        m[norm(canon)] = norm(canon)
        for s in syns or []:
            m[norm(s)] = norm(canon)
    return m


def canon(tag, amap: dict) -> str:
    n = norm(tag)
    return amap.get(n, n)


def month_index(x: str, today: dt.date) -> int:
    x = str(x).strip().lower()
    if x in ("", "present", "now"):
        return today.year * 12 + today.month - 1
    parts = x.split("-")
    return int(parts[0]) * 12 + (int(parts[1]) - 1 if len(parts) > 1 else 0)


def span_months(span, today: dt.date) -> tuple[int, int]:
    a, _, b = str(span).partition("..")
    start, end = month_index(a, today), month_index(b, today)
    if b.strip().isdigit():  # year-only end means through December
        end += 11
    return start, end


def union_months(intervals) -> int:
    total, cur = 0, None
    for s, e in sorted(intervals):
        if cur and s <= cur[1] + 1:
            cur[1] = max(cur[1], e)
        else:
            if cur:
                total += cur[1] - cur[0] + 1
            cur = [s, e]
    if cur:
        total += cur[1] - cur[0] + 1
    return total


def fmt_month(i: int) -> str:
    return f"{MONTHS[i % 12]} {i // 12}"


def fmt_period(span, today: dt.date) -> str:
    s, e = span_months(span, today)
    ended = str(span).partition("..")[2].strip().lower() not in ("", "present", "now")
    return f"{fmt_month(s)} - {fmt_month(e) if ended else 'Present'}"


def iter_atoms(facts: dict):
    for role in facts.get("roles") or []:
        for a in role.get("atoms") or []:
            yield role, a


# ---------------------------------------------------------------- validation & skills index

def validate(facts: dict, today: dt.date) -> list[str]:
    errs, seen, role_ids = [], set(), set()
    for r in facts.get("roles") or []:
        if r.get("id") in role_ids:
            errs.append(f"role id duplicate: {r.get('id')}")
        role_ids.add(r.get("id"))
        for k in ("id", "title", "org", "span"):
            if not r.get(k):
                errs.append(f"role {r.get('id', '?')}: missing {k}")
        try:
            span_months(r.get("span", ""), today)
        except (ValueError, IndexError):
            errs.append(f"role {r.get('id', '?')}: bad span {r.get('span')!r} (use YYYY-MM..YYYY-MM or ..present)")
        for a in r.get("atoms") or []:
            i = a.get("id")
            if not i or i in seen:
                errs.append(f"atom id missing or duplicate: {i}")
            seen.add(i)
            if not a.get("say"):
                errs.append(f"{i}: missing say")
            if not a.get("tags"):
                errs.append(f"{i}: no tags")
            if a.get("status", "unconfirmed") not in STATUS:
                errs.append(f"{i}: status must be one of {sorted(STATUS)}")
            if a.get("depth", "used") not in DEPTH:
                errs.append(f"{i}: depth must be one of {list(DEPTH)}")
    return errs


def build_index(facts: dict, today: dt.date) -> dict:
    amap = alias_map(facts)
    idx: dict = {}
    for role, a in iter_atoms(facts):
        if a.get("status", "unconfirmed") not in USABLE:
            continue
        span = span_months(a.get("span") or role["span"], today)
        for t in a.get("tags") or []:
            e = idx.setdefault(canon(t, amap), {"iv": [], "depth": 0, "atoms": [], "end": 0, "cred": False})
            if DEPTH.get(a.get("depth", "used"), 1) > 0 and not a.get("no_years"):  # exposure (a POC) or an undated claim is not years of experience
                e["iv"].append(span)
            e["depth"] = max(e["depth"], DEPTH.get(a.get("depth", "used"), 1))
            e["atoms"].append(a["id"])
            e["end"] = max(e["end"], span[1])
    now = today.year * 12 + today.month - 1
    for e in idx.values():
        e["years"] = round(union_months(e["iv"]) / 12, 1)
        e["last"] = "present" if e["end"] >= now else f"{e['end'] // 12}-{e['end'] % 12 + 1:02d}"
    for c in (facts.get("credentials") or []) + (facts.get("education") or []):
        for t in c.get("tags") or []:
            e = idx.setdefault(canon(t, amap), {"iv": [], "depth": 0, "atoms": [], "end": 0, "years": 0.0, "last": str(c.get("year", "")), "cred": True})
            e["cred"] = True
    return idx


DEPTH_NAME = {v: k for k, v in DEPTH.items()}


def pending_from_facts(facts: dict, amap: dict) -> dict:
    """Tags of atoms the person has not confirmed, each with the atom that carries it: the exact question `match` should ask."""
    pending: dict = {}
    for _, a in iter_atoms(facts):
        if a.get("status", "unconfirmed") not in USABLE:
            for t in a.get("tags") or []:
                pending.setdefault(canon(t, amap), []).append(f"{a['id']} ({a.get('status', 'unconfirmed')})")
    return pending


def render_skills_md(facts: dict, today: dt.date) -> str:
    """skills.md holds everything scoring and linting need, so neither has to read the facts (54 KB for a 12-year career):
    the tag table with a few evidence atom ids per tag, credentials, aliases, unconfirmed atoms, and the career length in months."""
    idx = build_index(facts, today)
    rows = sorted(idx.items(), key=lambda kv: (-kv[1]["years"], kv[0]))
    out = [f"<!-- GENERATED by career.py skills on {today}. Do not edit; edit the facts. -->",
           "# Skills index", "tag|yrs|last|depth|atoms|evidence", "-|-|-|-|-|-"]
    for tag, e in rows:
        depth = "cert" if e["cred"] and not e["atoms"] else DEPTH_NAME[e["depth"]]
        out.append(f"{tag}|{e['years']:g}|{e['last']}|{depth}|{len(e['atoms'])}|{'+'.join(e['atoms'][:3])}")
    creds = facts.get("credentials") or []
    if creds:
        out += ["", "# Credentials"] + [f"- {c.get('name')} ({c.get('issuer', '')}, {c.get('year', '')})" for c in creds]
    aliases = {k: v for k, v in (facts.get("aliases") or {}).items() if v}
    if aliases:
        out += ["", "# Aliases"] + [f"{k}: {', '.join(str(s) for s in v)}" for k, v in aliases.items()]
    pending = pending_from_facts(facts, alias_map(facts))
    if pending:
        out += ["", "# Pending"] + [f"{t}: {'; '.join(v)}" for t, v in sorted(pending.items())]
    roles = facts.get("roles") or []
    if roles:
        # Which fragment holds which atom: the agent opens `facts - <role id>` for the roles it needs and never the whole career.
        out += ["", "# Roles", "id|title|org|span|atoms", "-|-|-|-|-"]
        out += [f"{r['id']}|{r.get('title', '')}|{r.get('org', '')}|{r.get('span', '')}|{' '.join(str(a['id']) for a in r.get('atoms') or [])}" for r in roles]
    months = union_months([span_months(r["span"], today) for r in roles])
    out += ["", "# Career", f"career_months: {months}"]
    return "\n".join(out) + "\n"


def parse_skills_md(text: str) -> dict:
    """The inverse of render_skills_md, for callers that hold only the index: the hosted service scores and lints from it
    without ever receiving the facts. Older indexes (no evidence column, no aliases) still parse."""
    idx: dict = {}
    aliases: dict = {}
    pending: dict = {}
    roles: list = []
    months = None
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("# "):
            section = line[2:].strip().lower()
            continue
        if not line or line.startswith("<!--"):
            continue
        if section == "skills index":
            if line.startswith(("tag|", "-|")):
                continue
            f = line.split("|")
            if len(f) < 5:
                continue
            tag, depth = f[0], f[3]
            evidence = [x for x in (f[5].split("+") if len(f) > 5 else []) if x]
            count = int(f[4])
            if depth != "cert" and count and not evidence:        # written before the evidence column existed
                evidence = ["(atom)"] * min(count, 3)
            idx[tag] = {"iv": [], "depth": DEPTH.get(depth, 0), "atoms": evidence, "end": 0,
                        "years": float(f[1]), "last": f[2], "cred": depth == "cert"}
        elif section in ("aliases", "pending"):
            key, _, val = line.partition(":")
            if section == "aliases":
                aliases[key.strip()] = [s.strip() for s in val.split(",") if s.strip()]
            else:
                pending[key.strip()] = [s.strip() for s in val.split(";") if s.strip()]
        elif section == "roles":
            f = line.split("|")
            if len(f) >= 5 and not f[0].startswith("-") and f[0] != "id":
                roles.append({"id": f[0], "title": f[1], "org": f[2], "span": f[3], "atoms": f[4].split()})
        elif section == "career" and line.startswith("career_months:"):
            months = int(line.partition(":")[2])
    return {"idx": idx, "aliases": aliases, "amap": alias_map({"aliases": aliases}), "pending": pending, "career_months": months, "roles": roles}


def cmd_skills(ctx: Ctx, args):
    errs = validate(ctx.facts, ctx.today)
    if errs:
        print("facts.md problems:\n  " + "\n  ".join(errs), file=sys.stderr)
        return 1
    (ctx.root / "skills.md").write_text(render_skills_md(ctx.facts, ctx.today))
    print(f"skills.md: {len(build_index(ctx.facts, ctx.today))} tags, {sum(len(list(r.get('atoms') or [])) for r in ctx.facts.get('roles') or [])} atoms")
    return 0


# ---------------------------------------------------------------- match / select

def parse_reqs(s: str):
    out = []
    for part in s.split(","):
        bits = [b.strip() for b in part.split(":")]
        if not bits[0]:
            continue
        lvl = "must"
        if len(bits) > 1 and bits[1]:
            lvl = {"m": "must", "must": "must", "n": "nice", "nice": "nice"}.get(bits[1].lower(), "must")
        yrs = float(bits[2]) if len(bits) > 2 and bits[2] else None
        out.append((bits[0], lvl, yrs))
    return out


def req_status(tag, minyrs, idx, amap, never, gaps, pending=None):
    c = canon(tag, amap)
    if c in never:
        return "gap", "-", "-", "never_claim"
    e = idx.get(c)
    if e:
        ev = ",".join(e["atoms"][:3]) or "credential"
        if not e["atoms"]:
            return "met", "-", "cert", ev
        depth = DEPTH_NAME[e["depth"]]
        if e["depth"] == 0:
            return "partial", f"{e['years']:g}", depth, ev
        if minyrs and e["years"] < minyrs:
            st = "partial" if e["years"] >= 0.8 * minyrs else "short"
            return st, f"{e['years']:g}", depth, f"{ev} (needs {minyrs:g})"
        return "met", f"{e['years']:g}", depth, ev
    if c in gaps:
        return "gap", "-", "-", "known gap"
    if pending and c in pending:
        return "unasked", "-", "-", f"unverified: {'; '.join(pending[c][:2])}. Ask the candidate to confirm"
    return "unasked", "-", "-", "not in facts or known_gaps: ask the candidate"


def ceiling(rows, unasked_as: str) -> int:
    """Rule-based score cap; keeps the rubric semantics (1-10, strict)."""
    def st(r):
        return unasked_as if r["status"] == "unasked" else r["status"]
    musts = [r for r in rows if r["lvl"] == "must"]
    nices = [r for r in rows if r["lvl"] == "nice"]
    gap = sum(1 for r in musts if st(r) == "gap")
    short = sum(1 for r in musts if st(r) == "short")
    part = sum(1 for r in musts if st(r) == "partial")
    if musts and gap / len(musts) > 0.5:
        return 2
    if short >= 1 or gap >= 2:
        return 4
    if gap == 1:
        return 6
    nice_missing = sum(1 for r in nices if st(r) != "met")
    if part:
        return 8 if part + nice_missing <= 2 else 7
    return {0: 10, 1: 9, 2: 8}.get(nice_missing, 7)


def note_if_empty(ctx: Ctx):
    if not ctx.facts.get("roles"):
        print("note: facts.md has no roles yet, so nothing can be scored or selected. Run the intake workflow first (workflows/intake.md).", file=sys.stderr)


def match_table(idx: dict, amap: dict, profile: dict, pending: dict, req: str):
    """Score a requirement list against a skills index: (rows, strict ceiling, lenient ceiling, printable table).
    Shared by the CLI (index built from facts.md) and the hosted service (index parsed from skills.md)."""
    never = {canon(x, amap) for x in profile.get("never_claim") or []}
    gaps = {canon(x, amap) for x in profile.get("known_gaps") or []}
    pending = {k: list(v) for k, v in pending.items()}
    for tag, note in (profile.get("pending") or {}).items():  # things the person said but has not yet tied to a job
        pending.setdefault(canon(tag, amap), []).append(str(note).rstrip(". "))
    rows = []
    for tag, lvl, yrs in parse_reqs(req):
        st, y, d, ev = req_status(tag, yrs, idx, amap, never, gaps, pending)
        rows.append({"tag": tag, "lvl": lvl, "status": st, "yrs": y, "depth": d, "ev": ev})
    strict, lenient = ceiling(rows, "gap"), ceiling(rows, "met")
    line = f"ceiling: {strict}"
    if strict != lenient:
        line += f" (up to {lenient} if every 'unasked' turns out to be met)"
    lines = ["req|lvl|status|yrs|depth|evidence"]
    lines += [f"{r['tag']}|{r['lvl']}|{r['status']}|{r['yrs']}|{r['depth']}|{r['ev']}" for r in rows]
    lines.append(line + "  -> final score is the ceiling or one point below, with a stated reason")
    return rows, strict, lenient, "\n".join(lines)


def cmd_match(ctx: Ctx, args):
    note_if_empty(ctx)
    amap = alias_map(ctx.facts)
    _, _, _, table = match_table(build_index(ctx.facts, ctx.today), amap, ctx.profile, pending_from_facts(ctx.facts, amap), args.req)
    print(table)
    return 0


def recency_key(role, today):
    return -span_months(role["span"], today)[1]


def cmd_select(ctx: Ctx, args):
    note_if_empty(ctx)
    amap = alias_map(ctx.facts)
    want = {canon(t, amap) for t, _, _ in parse_reqs(args.tags)}
    roles = sorted(ctx.facts.get("roles") or [], key=lambda r: recency_key(r, ctx.today))
    for n, role in enumerate(roles):
        cap = args.cap or (6 if n < 2 else 3)
        scored = []
        for a in role.get("atoms") or []:
            if a.get("status", "unconfirmed") not in USABLE:
                continue
            only = {canon(t, amap) for t in a.get("only_for") or []}
            if only and not only & want:  # conditional atom (e.g. salon wording): only when the posting fits
                continue
            overlap = len({canon(t, amap) for t in a.get("tags") or []} & want)
            scored.append((overlap, DEPTH.get(a.get("depth", "used"), 1), a))
        scored.sort(key=lambda x: (-x[0], -x[1]))
        keep = [s for s in scored if s[0] > 0][:cap]
        if not keep and n < 2:  # recent roles should not come out blank
            keep = scored[:2]
        print(f"## {role['id']} | {role['title']} | {role['org']} | {role['span']}")
        if role.get("context"):
            print(f"   context: {role['context']}")
        if not keep:
            print("   (no tag overlap: omit or compress this role)")
        for ov, _, a in keep:
            mark = " [no figure]" if a.get("status") == "needs_number" else ""
            note = f"  // {a['note']}" if a.get("note") else ""
            print(f"- {a['id']} [{a.get('depth', 'used')}, {ov} match]{mark} {a['say']}{note}")
    return 0


# ---------------------------------------------------------------- lint / build

BANNED = [r"\bspearhead\w*", r"\bleverag(?:e|ed|es|ing)\b", r"\borchestrat\w*", r"\butiliz\w*",
          r"\brobust\b", r"\bseamless(?:ly)?\b", r"\bcutting[- ]edge\b", r"\bproven track record\b",
          r"\bresults[- ]driven\b", r"\bpassionate\b", r"\bsynerg\w*", r"\bdynamic\b",
          r"\bdetail[- ]oriented\b", r"\bresponsible for\b", r"\bworked on\b", r"\bseasoned\b",
          r"\bholistic\b", r"\bpivotal\b", r"\bfoster\w*", r"\bdelve\w*", r"\bmeticulous\w*",
          r"\btestament\b", r"\bunderscor\w*", r"\bshowcas\w*", r"\bensur(?:e|ed|es|ing)\b",
          r"\bin today's\b", r"\bfast-paced\b"]
TAIL = re.compile(r",\s+(?:enabling|ensuring|resulting in|driving|allowing|improving|reducing|increasing|"
                  r"leading to|making|helping|providing|delivering)\b", re.I)
NUM = re.compile(r"(?<![A-Za-z0-9.])(\d[\d,]*(?:\.\d+)?)\s*([kKmMbB](?![a-z]))?")
YEARS = re.compile(r"(\d+(?:\.\d+)?)\+?[\s-]*(?:years?|yrs?)\b", re.I)
TERM = re.compile(r"\b[A-Z][A-Za-z0-9+#]*[A-Za-z0-9+#]\b")
STOP_TERMS = set(MONTHS) | {"i", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "q1", "q2", "q3", "q4"}


STOP_WORDS = set("""a an the and or of to in on at for from with without by as is are was were be been being that this these those it its
into across about over per than then also both each all any not no which who whom whose their there our my your i we you they them he she his her
would will can could should has have had up out off more most very just only""".split())
NUMWORDS = re.compile(r"\b(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|dozens?|hundreds?|thousands?|millions?|half|double[ds]?|triple[ds]?)\b", re.I)

NUMVAL = {w: float(i) for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve".split())}
NUMVAL["dozen"] = 12.0


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z][a-z0-9+#']*", text.lower()) if len(w) >= 3 and w not in STOP_WORDS]


def _stem(w: str) -> str:
    return w if len(w) <= 5 else w[:5]  # crude but enough to treat reconcile/reconciles/reconciliation as one word


def novel_words(text: str, vocab: str) -> list[str]:
    """Content words in `text` that the source atom(s) never used: the fingerprint of an embellished claim."""
    have = {_stem(w) for w in _words(vocab)}
    out: list[str] = []
    for w in _words(text):
        if _stem(w) not in have and w not in out:
            out.append(w)
    return out


def known_term(word: str, corpus: set) -> bool:
    w = word.lower()
    return w in corpus or w + "s" in corpus or w + "es" in corpus or (w.endswith("s") and w[:-1] in corpus)


def terms(text: str) -> list[str]:
    """Capitalised tool-like words, ignoring the first word of each sentence."""
    out = []
    for m in TERM.finditer(text):
        before = text[:m.start()].rstrip()
        if before and not before.endswith((".", "!", "?")):
            out.append(m.group(0))
    return out


def numbers_in(text: str) -> set:
    out = set()
    for m in NUM.finditer(text):
        v = float(m.group(1).replace(",", ""))
        mult = {"k": 1e3, "m": 1e6, "b": 1e9}.get((m.group(2) or "").lower(), 1)
        if mult == 1 and 1990 <= v <= 2100:
            continue
        out.add(round(v * mult, 2))
    return out


def corpus_words(facts: dict, profile: dict) -> set:
    blob = json.dumps(facts, default=str) + json.dumps(profile, default=str)
    return set(re.findall(r"[a-z0-9+#]+", blob.lower()))


LETTER_BANNED = [r"\bI am writing to\b", r"\bI am (?:excited|thrilled|delighted|eager|pleased)\b", r"\b(?:excited|thrilled|eager) (?:to|about)\b",
                 r"\bperfect (?:fit|candidate)\b", r"\balign(?:s|ed|ment)? (?:perfectly |closely |well )?with\b",
                 r"\bthank you for (?:your )?(?:time|consideration)\b", r"\bopportunity to (?:contribute|join)\b", r"\bpassion for\b",
                 r"\bI believe (?:I|my)\b", r"\bunique (?:blend|combination|set of)\b", r"\bproven ability\b"]


def prose_issues(texts, never, first_person_ok=False, extra_banned=()):
    """Style and never_claim checks shared by the resume and the cover letter."""
    out = []
    for where, text in texts:
        for rx in never:
            if rx.search(text):
                out.append(("E", where, f"never_claim hit: '{rx.pattern[2:-2]}'"))
        for pat in (*BANNED, *extra_banned):
            m = re.search(pat, text, re.I)
            if m:
                out.append(("W", where, f"banned/AI-tell phrase '{m.group(0)}'"))
        if re.search(r"[—–]| -- ", text):
            out.append(("W", where, "dash used as punctuation; use a comma or period"))
        if TAIL.search(text):
            out.append(("W", where, "trailing '..., enabling/ensuring/resulting in' clause"))
        if not first_person_ok and re.search(r"\b(?:I|my|me)\b", text):
            out.append(("W", where, "first-person pronoun"))
    return out


def year_allowed(ctx: Ctx, roles: dict, idx: dict, career_months: int | None = None):
    """'N years' claims may equal the computed career length or any skill's computed years.
    `career_months` replaces the sum over `roles` when the caller holds only some of the roles (the hosted service)."""
    total = (career_months if career_months is not None else union_months([span_months(r["span"], ctx.today) for r in roles.values()])) / 12
    ok = {float(int(total)), float(round(total))}
    for e in idx.values():
        ok |= {float(int(e["years"])), float(round(e["years"]))}
    return ok, total


def lint(ctx: Ctx, sel: dict, idx: dict | None = None, career_months: int | None = None):
    """Check a resume selection. With no arguments everything is derived from the facts. The hosted service passes the
    index parsed from skills.md and the career length, and supplies only the roles and atoms the selection cites."""
    facts, profile = ctx.facts, ctx.profile
    amap = alias_map(facts)
    corpus = corpus_words(facts, profile)
    if idx is None:
        idx = build_index(facts, ctx.today)
    else:
        corpus |= set(re.findall(r"[a-z0-9+#]+", " ".join(idx).lower()))
    roles = {r["id"]: r for r in facts.get("roles") or []}
    by_id = {a["id"]: (r, a) for r, a in iter_atoms(facts)}
    never = [re.compile(r"\b" + re.escape(str(x)) + r"\b", re.I) for x in profile.get("never_claim") or []]
    issues: list[tuple[str, str, str]] = []

    def add(level, where, msg):
        issues.append((level, where, msg))

    texts: list[tuple[str, str]] = []
    summary = (sel.get("summary") or "").strip()
    if summary:
        texts.append(("summary", summary))
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", summary) if s]
        if len(sentences) > 2:
            add("W", "summary", f"{len(sentences)} sentences; keep to 2")
        if len(summary.split()) > 55:
            add("W", "summary", f"{len(summary.split())} words; keep under 55")
        # a summary may cite only figures found in atoms/context; "N years" must match computed career/skill length
        year_ok, total_years = year_allowed(ctx, roles, idx, career_months)
        ok = set()
        for r in roles.values():
            ok |= numbers_in(r.get("context", ""))
        for _, a in by_id.values():
            ok |= numbers_in(a.get("say", ""))
            for v in (a.get("nums") or {}).values():
                ok |= numbers_in(str(v))
        for n in sorted({float(m.group(1)) for m in YEARS.finditer(summary)} - year_ok):
            add("E", "summary", f"number {n:g} is not supported by facts (career length computes to {total_years:.1f} years)")
        for n in sorted(numbers_in(YEARS.sub(" ", summary)) - ok):
            add("E", "summary", f"number {n:g} is not supported by facts")
        for w in terms(summary):
            if not known_term(w, corpus) and w.lower() not in STOP_TERMS:
                add("W", "summary", f"term '{w}' appears nowhere in facts.md/profile.md")

    all_bullets: list[str] = []
    for role_sel in sel.get("roles") or []:
        rid = role_sel.get("id")
        role = roles.get(rid)
        if not role:
            add("E", f"role {rid}", "not in facts.md")
            continue
        allowed_titles = [role["title"], *(role.get("framings") or [])]
        if role_sel.get("title") and role_sel["title"] not in allowed_titles:
            add("E", rid, f"title '{role_sel['title']}' is not the real title or an allowed framing: {allowed_titles}")
        firsts, counts = [], []
        for i, b in enumerate(role_sel.get("bullets") or [], 1):
            where = f"{rid}#{i}"
            text = (b.get("text") or "").strip()
            ids = b.get("atoms") or ([b["atom"]] if b.get("atom") else [])
            if not ids:
                add("E", where, "no atom id: every bullet must trace to an atom")
            allowed = numbers_in(role.get("context", ""))
            for aid in ids:
                pair = by_id.get(aid)
                if not pair:
                    add("E", where, f"atom {aid} not in facts.md")
                    continue
                arole, atom = pair
                if atom.get("only_for"):
                    add("W", where, f"atom {aid} is conditional (only for {', '.join(map(str, atom['only_for']))}): keep it only if the posting fits")
                if arole["id"] != rid:
                    add("E", where, f"atom {aid} belongs to role {arole['id']}, not {rid}")
                if atom.get("status", "unconfirmed") not in USABLE:
                    add("E", where, f"atom {aid} has status {atom.get('status', 'unconfirmed')}; not usable")
                allowed |= numbers_in(atom.get("say", ""))
                for v in (atom.get("nums") or {}).values():
                    allowed |= numbers_in(str(v))
            for n in sorted(numbers_in(text) - allowed):
                add("E", where, f"number {n:g} is not in the atom(s); if it is true, add it to the atom's say/nums")
            vocab = " ".join([role.get("title", ""), role.get("org", ""), role.get("context", "")] +
                             [f"{a.get('say', '')} {' '.join(map(str, a.get('tags') or []))}" for _, a in (by_id[i] for i in ids if i in by_id)])
            for nw in sorted({m.group(0).lower() for m in NUMWORDS.finditer(text)} - {m.group(0).lower() for m in NUMWORDS.finditer(vocab)}):
                if NUMVAL.get(nw) not in allowed:  # 'twelve' is fine when the atom says 12
                    add("E", where, f"number word '{nw}' is not in the atom(s)")
            extra = novel_words(text, vocab)
            if ids and len(extra) >= 3:
                add("W", where, f"adds wording the atom never used: {', '.join(extra[:6])}. If that is a new claim, put it in the atom first; otherwise cut it")
            for w in terms(text):
                if not known_term(w, corpus) and w.lower() not in STOP_TERMS:
                    add("W", where, f"term '{w}' appears nowhere in facts.md/profile.md")
            n_words = len(text.split())
            if n_words > 35:
                add("W", where, f"{n_words} words; tighten")
            if 0 < n_words < 5:
                add("W", where, "very short bullet")
            firsts.append(text.split()[0].lower() if text else "")
            counts.append(n_words)
            texts.append((where, text))
            all_bullets.append(text)
        dup = {f for f in firsts if f and firsts.count(f) > 1}
        if dup:
            add("W", rid, f"repeated leading word(s): {', '.join(sorted(dup))}")
        if len(counts) >= 4 and statistics.pstdev(counts) < 2.5:
            add("W", rid, "bullets are near-uniform in length; vary the rhythm")

    if len(all_bullets) >= 5 and all(numbers_in(b) for b in all_bullets):
        add("W", "all", "every bullet has a metric; let a few stand without one")
    trip = [b for b in all_bullets if re.search(r"[\w/+.-]+(?: [\w/+.-]+)?, [\w/+.-]+(?: [\w/+.-]+)?,? and [\w/+.-]+", b)]
    if len(trip) >= 3 and len(trip) / len(all_bullets) > 0.4:
        add("W", "all", f"{len(trip)} bullets use an 'A, B, and C' list; vary the structure")

    for group in sel.get("skills") or []:
        for item in group.get("items") or []:
            # "GCP and AWS (general use and troubleshooting)" is two skills with a qualifier; every part must be on file
            base = re.sub(r"\s*\(.*?\)", "", item)
            for part in [x for x in re.split(r"\s+and\s+|,|/", base) if x.strip()]:
                if canon(part, amap) not in idx:
                    where = f" (in '{item}')" if part.strip() != item else ""
                    add("E", f"skills/{group.get('name')}", f"'{part.strip()}'{where} is not in skills.md (verified atoms or credentials)")
        texts.append((f"skills/{group.get('name')}", " ".join(group.get("items") or [])))

    issues += prose_issues(texts, never)
    return issues


def letter_html(ctx: Ctx, letter: dict):
    """RR cover-letter items are HTML: an address block, and a body holding salutation, paragraphs, closing and signature."""
    company = (letter.get("target") or {}).get("company") or ""
    lines = letter.get("recipient") or ["Hiring Manager", company]
    lines = [lines] if isinstance(lines, str) else lines
    today = f"{ctx.today:%B} {ctx.today.day}, {ctx.today.year}"
    # Reactive Resume prints no resume header on a cover letter, so the letter carries its own letterhead
    prof = ctx.profile
    contact = " | ".join(str(x) for x in (prof.get("email"), prof.get("phone")) if x)
    head = [x for x in ((f"<strong>{html.escape(str(prof['name']))}</strong>" if prof.get("name") else ""), html.escape(contact),
                        html.escape(str(prof.get("location") or ""))) if x]
    sender = f"<p>{'<br>'.join(head)}</p>" if head else ""
    recipient = f"{sender}<p>{today}</p><p>" + "<br>".join(html.escape(str(x)) for x in lines if x) + "</p><p></p>"
    parts = [f"<p>{html.escape(letter.get('salutation') or 'Dear Hiring Manager,')}</p>"]
    parts += [f"<p>{html.escape(p['text'].strip())}</p>" for p in letter.get("paragraphs") or []]
    parts.append(f"<p>{html.escape(letter.get('closing') or 'Sincerely,')}<br>{html.escape(ctx.profile.get('name', ''))}</p>")
    return recipient, "".join(parts)


def letter_text(ctx: Ctx, letter: dict) -> str:
    company = (letter.get("target") or {}).get("company") or ""
    lines = letter.get("recipient") or ["Hiring Manager", company]
    lines = [lines] if isinstance(lines, str) else lines
    prof = ctx.profile
    letterhead = [x for x in (prof.get("name"), " | ".join(str(v) for v in (prof.get("email"), prof.get("phone")) if v), prof.get("location")) if x]
    out = (letterhead + [""] if letterhead else []) + [f"{ctx.today:%B} {ctx.today.day}, {ctx.today.year}", ""] + [x for x in lines if x] + ["", letter.get("salutation") or "Dear Hiring Manager,", ""]
    for p in letter.get("paragraphs") or []:
        out += [p["text"].strip(), ""]
    return "\n".join(out + [letter.get("closing") or "Sincerely,", ctx.profile.get("name", "")]) + "\n"


INTENT = re.compile(r"\b(?:would|welcome|hope|glad|happy|look forward|love|talk|discuss|conversation|chat|appl(?:y|ying|ied)|interested)\b", re.I)


def lint_letter(ctx: Ctx, letter: dict, job: Path | None, idx: dict | None = None, career_months: int | None = None, jd: str | None = None):
    """Check a cover letter. `idx`, `career_months` and `jd` let the hosted service supply the parts it holds in memory
    (the skills index, the career length and the posting text) instead of reading the facts and a job folder."""
    facts, profile = ctx.facts, ctx.profile
    extra_vocab = ""
    if idx is None:
        idx = build_index(facts, ctx.today)
    else:
        extra_vocab = " ".join(idx)
    roles = {r["id"]: r for r in facts.get("roles") or []}
    by_id = {a["id"]: (r, a) for r, a in iter_atoms(facts)}
    never = [re.compile(r"\b" + re.escape(str(x)) + r"\b", re.I) for x in profile.get("never_claim") or []]
    if jd is None:
        jd = (job / "jd.md").read_text() if job and (job / "jd.md").exists() else ""
    target = letter.get("target") or {}
    corpus = corpus_words(facts, profile) | set(re.findall(r"[a-z0-9+#]+", (jd + " " + " ".join(map(str, target.values())) + " " + extra_vocab).lower()))
    year_ok, total_years = year_allowed(ctx, roles, idx, career_months)
    jd_nums = numbers_in(YEARS.sub(" ", jd))
    issues: list[tuple[str, str, str]] = []
    if not jd:
        issues.append(("W", "letter", "no jd.md in the job folder: statements about the company cannot be checked"))
    if profile.get("name") in (None, "", "Your Name"):
        issues.append(("W", "letter", "profile.md has no real name: the signature would be blank or a placeholder"))
    paras = letter.get("paragraphs") or []
    texts = [("salutation", letter.get("salutation") or ""), ("closing", letter.get("closing") or "")]
    for i, para in enumerate(paras, 1):
        where, text, ids = f"para {i}", (para.get("text") or "").strip(), para.get("atoms") or []
        texts.append((where, text))
        if not ids and not para.get("jd"):
            issues.append(("E", where, "cites no atoms and is not marked jd: true; every claim about you needs an atom"))
        allowed = set(jd_nums) if para.get("jd") else set()
        for aid in ids:
            pair = by_id.get(aid)
            if not pair:
                issues.append(("E", where, f"atom {aid} not in facts.md"))
                continue
            arole, atom = pair
            if atom.get("status", "unconfirmed") not in USABLE:
                issues.append(("E", where, f"atom {aid} has status {atom.get('status', 'unconfirmed')}; not usable"))
            if atom.get("only_for"):
                issues.append(("W", where, f"atom {aid} is conditional (only for {', '.join(map(str, atom['only_for']))}): keep it only if the posting fits"))
            allowed |= numbers_in(atom.get("say", "")) | numbers_in(arole.get("context", ""))
            for v in (atom.get("nums") or {}).values():
                allowed |= numbers_in(str(v))
        for n in sorted({float(m.group(1)) for m in YEARS.finditer(text)} - year_ok):
            issues.append(("E", where, f"number {n:g} is not supported by facts (career length computes to {total_years:.1f} years)"))
        for n in sorted(numbers_in(YEARS.sub(" ", text)) - allowed):
            issues.append(("E", where, f"number {n:g} is not in the cited atoms" + (" or jd.md" if para.get("jd") else "")))
        if ids and not para.get("jd"):
            cited = [by_id[i] for i in ids if i in by_id]
            vocab = " ".join([f"{a.get('say', '')} {' '.join(map(str, a.get('tags') or []))} {r.get('title', '')} {r.get('org', '')} {r.get('context', '')}" for r, a in cited] + [" ".join(map(str, target.values()))])
            for nw in sorted({m.group(0).lower() for m in NUMWORDS.finditer(text)} - {m.group(0).lower() for m in NUMWORDS.finditer(vocab)}):
                if NUMVAL.get(nw) not in allowed:
                    issues.append(("E", where, f"number word '{nw}' is not in the cited atoms"))
            for sent in re.split(r"(?<=[.!?])\s+", text):
                extra = novel_words(sent, vocab)
                if len(extra) >= 5:
                    issues.append(("W", where, f"a sentence adds wording the cited atoms never used: {', '.join(extra[:6])}. Cut it or put the fact in an atom first"))
        for w in terms(text):
            if not known_term(w, corpus) and w.lower() not in STOP_TERMS:
                issues.append(("W", where, f"term '{w}' appears nowhere in facts.md, profile.md or jd.md"))
        if para.get("jd"):  # a jd-only paragraph may state intent, but any other statement about "I" or "my" is a claim that needs an atom
            for sent in re.split(r"(?<=[.!?])\s+", text):
                if re.search(r"\b(?:I|I'm|I've|my|me)\b", sent) and not INTENT.search(sent):
                    issues.append(("W", where, f"claim about you in a jd-only paragraph: '{sent[:70]}'. Cite an atom, or cut it"))
    words = sum(len(t.split()) for w, t in texts if w.startswith("para"))
    if not 90 <= words <= 320:
        issues.append(("W", "letter", f"{words} words in the body; aim for roughly 150 to 300"))
    if not 3 <= len(paras) <= 4:
        issues.append(("W", "letter", f"{len(paras)} paragraphs; three or four reads best"))
    return issues + prose_issues(texts, never, first_person_ok=True, extra_banned=LETTER_BANNED)


def load_selection(ctx: Ctx, arg: str) -> tuple[Path, dict]:
    p = Path(arg).expanduser()
    p = p if p.is_file() else ctx.job_dir(arg) / "selection.yml"
    if not p.exists():
        die(f"{p} not found")
    return p, yaml.safe_load(p.read_text()) or {}


def render_text(ctx: Ctx, sel: dict) -> str:
    roles = {r["id"]: r for r in ctx.facts.get("roles") or []}
    p = ctx.profile
    out = [f"# {p.get('name', '')}", p.get("headline", ""), "", "## Summary", sel.get("summary", ""), "", "## Skills"]
    out += [f"**{g['name']}:** {', '.join(g.get('items') or [])}" for g in sel.get("skills") or []]
    out += ["", "## Experience"]
    for rs in sel.get("roles") or []:
        r = roles[rs["id"]]
        out += ["", f"### {rs.get('title') or r['title']}, {r['org']} ({fmt_period(r['span'], ctx.today)})"]
        out += [f"- {b['text']}" for b in rs.get("bullets") or []]
    return "\n".join(out) + "\n"


def cmd_build(ctx: Ctx, args):
    path, sel = load_selection(ctx, args.job)
    issues = lint(ctx, sel)
    for lv, where, msg in issues:
        print(f"{lv} {where}: {msg}")
    errors = sum(1 for i in issues if i[0] == "E")
    warns = len(issues) - errors
    (path.parent / "resume.md").write_text(render_text(ctx, sel))
    print(f"{errors} error(s), {warns} warning(s); wrote {path.parent / 'resume.md'}")
    return 1 if errors or (args.strict and warns) else 0


# ---------------------------------------------------------------- Reactive Resume API

# Cloudflare and similar proxies answer Python's default urllib User-Agent with a 403 "Error 1010", so name ourselves.
USER_AGENT = "career-architect/2"


class ApiError(Exception):
    def __init__(self, status, body, url=""):
        low, hint = body.lower(), ""
        if "cloudflare" in low or "error 1010" in low:
            hint = " (Cloudflare blocked the request: check WAF/bot rules or an Access policy covering /api/openapi)"
        elif status in (401, 403) and body.lstrip().startswith("<"):
            hint = " (an HTML answer means a login proxy sits in front: exempt /api/openapi or use a service token)"
        elif status == 401 and "unauthorized" in low:
            hint = (" (the server rejected the API key. Create a new key in Reactive Resume under Settings > API Keys on this same instance"
                    " (keys expire and are per instance), then run: bash ~/Projects/career-architect/setup.sh --rekey)")
        super().__init__(f"{url} -> HTTP {status}: {body[:200]}{hint}")
        self.status, self.body = status, body


def _is_local(host: str) -> bool:
    if host == "localhost" or host.endswith((".local", ".lan", ".internal", ".home.arpa")) or "." not in host:
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback
    except ValueError:
        return False


def normalize_url(u: str) -> str:
    """https unless the host is local/private. A public host answers http with a redirect, which would break POST/PATCH."""
    u = u.strip().rstrip("/")
    if "://" not in u:
        u = "https://" + u
    p = urllib.parse.urlsplit(u)
    scheme = "http" if p.scheme == "http" and _is_local(p.hostname or "") else "https"
    path = p.path.rstrip("/")
    if path.endswith("/api/openapi"):  # tolerate the spec's server URL being pasted
        path = path[: -len("/api/openapi")]
    return urllib.parse.urlunsplit((scheme, p.netloc, path, "", ""))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None  # surface the 3xx instead of silently re-sending a POST/PATCH as a GET


_opener = urllib.request.build_opener(_NoRedirect)


def rr_cfg(ctx: Ctx) -> dict:
    if getattr(ctx, "_rr", None):
        return ctx._rr
    conf = {}
    if CONF.exists():
        if CONF.stat().st_mode & 0o077:
            print(f"warning: {CONF} is readable by other users; run chmod 600 on it", file=sys.stderr)
        for line in CONF.read_text().splitlines():
            k, _, v = line.partition("=")
            conf[k.strip()] = v.strip().strip("'\"")
    # The URL is not a secret and has one home, profile.md. $RR_URL overrides it; a stale RR_URL left in rr.env is the last resort.
    for src, val in (("$RR_URL", os.environ.get("RR_URL")), ("profile.md", ctx.profile.get("rr_url")), ("rr.env", conf.get("RR_URL"))):
        if val:
            break
    else:
        die(f"no Reactive Resume URL: set rr_url in {ctx.root / 'profile.md'}")
    ctx._rr = {"url": normalize_url(val), "src": src, "key": os.environ.get("RR_API_KEY") or conf.get("RR_API_KEY")}
    return ctx._rr


def api(ctx: Ctx, method: str, path: str, body=None, raw=False, multipart=None, auth=True, root=False):
    cfg = rr_cfg(ctx)
    if auth and not cfg["key"]:
        die(f"no API key: put RR_API_KEY=... in {CONF} (chmod 600). Never paste it into chat or the vault.")
    url = f"{cfg['url']}{'' if root else '/api/openapi'}{path}"
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if auth:
        headers["x-api-key"] = cfg["key"]
    data = None
    if multipart:
        boundary = uuid.uuid4().hex
        name, filename, blob = multipart
        data = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\n"
                f"Content-Type: application/pdf\r\n\r\n").encode() + blob + f"\r\n--{boundary}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with _opener.open(req, timeout=60) as r:
            blob = r.read()
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf8", "replace")
        if 300 <= e.code < 400:
            text = f"redirected to {e.headers.get('Location')}; set rr_url in profile.md to that exact address"
        raise ApiError(e.code, text, url)
    except OSError as e:
        die(f"cannot reach {cfg['url']}: {getattr(e, 'reason', e)}")
    if raw:
        return blob
    return json.loads(blob) if blob else None


def mcp_rpc(ctx: Ctx, method: str, params=None):
    """One JSON-RPC call to the Reactive Resume MCP endpoint (same x-api-key as the REST API). Used by `career check`;
    the MCP tools themselves are called by Claude, not by this script."""
    cfg = rr_cfg(ctx)
    if not cfg["key"]:
        die(f"no API key: put RR_API_KEY=... in {CONF} (chmod 600). Never paste it into chat or the vault.")
    url = f"{cfg['url']}/mcp"
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json", "Accept": "application/json, text/event-stream", "x-api-key": cfg["key"]}
    req = urllib.request.Request(url, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}).encode(), headers=headers, method="POST")
    try:
        with _opener.open(req, timeout=30) as r:
            text = r.read().decode("utf8", "replace")
    except urllib.error.HTTPError as e:
        raise ApiError(e.code, e.read().decode("utf8", "replace"), url)
    except OSError as e:
        die(f"cannot reach {cfg['url']}: {getattr(e, 'reason', e)}")
    # A streamable-HTTP server may answer with plain JSON or with one SSE `data:` event.
    payload = next((ln[5:].strip() for ln in text.splitlines() if ln.startswith("data:")), text.strip())
    try:
        msg = json.loads(payload)
    except ValueError:
        raise CheckFail(f"{url} did not answer with JSON-RPC: {text[:120]!r}")
    if msg.get("error"):
        raise CheckFail(f"{method}: {msg['error'].get('message', msg['error'])}")
    return msg.get("result") or {}


def as_list(resp):
    if isinstance(resp, list):
        return resp
    if isinstance(resp, dict):
        for k in ("items", "data", "applications", "resumes"):
            if isinstance(resp.get(k), list):
                return resp[k]
    return []


def cmd_resumes(ctx: Ctx, args):
    for r in as_list(api(ctx, "GET", "/resumes")):
        print(f"{r.get('id')} | {r.get('slug')} | {r.get('name')} | {','.join(r.get('tags') or [])}"
              f"{' | locked' if r.get('isLocked') else ''}")
    return 0


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def doc_title(ctx: Ctx, target: dict, kind: str = "Resume") -> str:
    """'Company - Role - Name Resume': the job title travels with the document so a recruiter, a Drive search
    and a downloaded file all show which role it was written for."""
    who = str(ctx.profile.get("name") or "").strip()
    return " - ".join(p for p in (target.get("company"), target.get("role"), f"{who} {kind}".strip()) if p)


def file_safe(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "-", s).strip()


def html_list(bullets) -> str:
    return "<ul>" + "".join(f"<li><p>{html.escape(b['text'])}</p></li>" for b in bullets) + "</ul>"


def build_items(ctx: Ctx, sel: dict, master: dict):
    """Experience and skills items shaped like the master's own items, so field names come from the instance."""
    sections = master["data"]["sections"]
    exp_tpl = (sections["experience"]["items"] or [{}])[0]
    skl_tpl = (sections["skills"]["items"] or [{}])[0]
    roles = {r["id"]: r for r in ctx.facts.get("roles") or []}
    exp = []
    for rs in sel.get("roles") or []:
        r = roles[rs["id"]]
        item = copy.deepcopy(exp_tpl)
        item.update({"id": str(uuid.uuid4()), "hidden": False, "company": r["org"], "position": rs.get("title") or r["title"],
                     "location": r.get("location", "Remote" if r.get("remote") else ""),
                     "period": fmt_period(r["span"], ctx.today), "description": html_list(rs.get("bullets") or []),
                     "roles": []})
        item["website"] = {"inlineLink": False, **(exp_tpl.get("website") or {}), "url": "", "label": ""}
        exp.append(item)
    skl = []
    for g in sel.get("skills") or []:
        item = copy.deepcopy(skl_tpl)
        item.update({"id": str(uuid.uuid4()), "hidden": False, "name": g["name"], "keywords": list(g.get("items") or [])})
        item.setdefault("icon", "")
        item.setdefault("iconColor", "")
        item.setdefault("proficiency", "")
        item.setdefault("level", 0)
        skl.append(item)
    return exp, skl


def _site(url: str = "", label: str = "") -> dict:
    return {"url": url, "label": label, "inlineLink": False}


def cert_items(creds: list) -> list:
    """One line per certification, always under its full official name: AI HRIS parsers match whole cert names,
    so 'Okta Certified Administrator, Professional and ...' would lose two of the three."""
    out = []
    for c in creds:
        name, issuer = str(c.get("name", "")), str(c.get("issuer", ""))
        out.append({"id": str(uuid.uuid4()), "hidden": False, "title": name,
                    "issuer": "" if issuer.lower() in name.lower() else issuer,  # "Okta" beside "Okta Certified ..." is a wasted column
                    "date": str(c.get("year", "")), "website": _site(), "description": ""})
    return out


def profile_ops(ctx: Ctx, master: dict) -> list:
    """Contact details, education, certifications and profile links come from profile.md and facts.md,
    so the Master only has to supply the template and design."""
    p, f, ops = ctx.profile, ctx.facts, []
    sections = master["data"].get("sections") or {}
    for k in ("name", "headline", "email", "phone", "location"):
        if p.get(k) and p[k] != "Your Name":
            ops.append({"op": "replace", "path": f"/basics/{k}", "value": str(p[k])})

    def put(name, items):
        if items:
            ops.append({"op": "replace", "path": f"/sections/{name}/items", "value": items})
            if (sections.get(name) or {}).get("hidden"):
                ops.append({"op": "replace", "path": f"/sections/{name}/hidden", "value": False})

    put("education", [{"id": str(uuid.uuid4()), "hidden": False, "school": e.get("school", ""), "degree": e.get("degree", ""),
                       "area": e.get("area", ""), "grade": e.get("grade", ""), "location": e.get("location", ""),
                       "period": str(e.get("period", "")), "website": _site(), "description": ""} for e in f.get("education") or []])
    put("certifications", cert_items(f.get("credentials") or []))
    links = []
    for key, icon in (("linkedin", "linkedin-logo"), ("github", "github-logo")):
        if p.get(key):
            url = str(p[key])
            links.append({"id": str(uuid.uuid4()), "icon": icon, "text": re.sub(r"^https?://(www\.)?", "", url).rstrip("/"), "link": url})
    if links:  # inline header links; the stacked Profiles section would only repeat them
        ops.append({"op": "replace", "path": "/basics/customFields", "value": links})
        ops.append({"op": "replace", "path": "/sections/profiles/items", "value": []})
        ops.append({"op": "replace", "path": "/sections/profiles/hidden", "value": True})
    return ops


def content_ops(ctx: Ctx, sel: dict, master: dict) -> list:
    """Everything a selection puts into a resume: summary, experience, skills, plus header, education and certifications."""
    exp, skl = build_items(ctx, sel, master)
    summary_path = "/summary/content" if isinstance(master["data"].get("summary"), dict) else "/summary"
    ops = [{"op": "replace", "path": summary_path, "value": f"<p>{html.escape(sel.get('summary') or '')}</p>"},
           {"op": "replace", "path": "/sections/experience/items", "value": exp},
           {"op": "replace", "path": "/sections/skills/items", "value": skl}]
    return ops + profile_ops(ctx, master)


DESIGN_KEYS = ("template", "page", "typography", "design", "layout")


def design_ops(master: dict) -> list:
    """Copy the Master's look onto a resume. Only on request, so a per-job template choice is never overwritten."""
    meta = master["data"].get("metadata") or {}
    return [{"op": "replace", "path": f"/metadata/{k}", "value": meta[k]} for k in DESIGN_KEYS if k in meta]


def us_defaults_ops(master: dict) -> list:
    """Reactive Resume defaults to A4 and a 1.5 line height; a US resume wants Letter and a tighter page (1.25 fits a 12-year history on two pages). Only while still at those defaults."""
    meta, ops = master["data"].get("metadata") or {}, []
    if (meta.get("page") or {}).get("format") == "a4":
        ops.append({"op": "replace", "path": "/metadata/page/format", "value": "letter"})
    if ((meta.get("typography") or {}).get("body") or {}).get("lineHeight") in (1.5, 1.35):  # 1.35 was an earlier default of this tool
        ops.append({"op": "replace", "path": "/metadata/typography/body/lineHeight", "value": 1.25})
    return ops


def cover_section_ops(resume: dict, master: dict | None) -> list:
    """Add a cover-letter section when the resume has none: a copy of the Master's if it has one, else a default. The section is
    deliberately left out of the page layout, which keeps the letter out of the resume PDF (verified on Reactive Resume 5.3.1)."""
    if any(c.get("type") == "cover-letter" for c in resume["data"].get("customSections") or []):
        return []
    src = next((c for c in ((master or {}).get("data") or {}).get("customSections") or [] if c.get("type") == "cover-letter"), None)
    sec = copy.deepcopy(src) if src else {"title": "Cover Letter", "icon": "", "columns": 1, "hidden": False, "showHeading": False,
                                          "keepTogether": True, "startOnNewPage": True, "type": "cover-letter", "items": []}
    sec["id"] = str(uuid.uuid4())
    sec["items"] = [{"id": str(uuid.uuid4()), "hidden": False, "recipient": "", "content": ""}]
    return [{"op": "add", "path": "/customSections/-", "value": sec}]


def cmd_push(ctx: Ctx, args):
    path, sel = load_selection(ctx, args.job)
    issues = lint(ctx, sel)
    errs = [i for i in issues if i[0] == "E"]
    if errs:
        for lv, where, msg in errs:
            print(f"{lv} {where}: {msg}")
        die("lint errors; fix them (or run `build`) before pushing", 1)
    job = path.parent
    target = sel.get("target") or {}
    if not (target.get("company") and target.get("role")):
        die("selection.yml needs target.company and target.role: the job title goes into the resume's name and PDF filename", 1)
    state_file = job / "rr.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    master_id = args.master or ctx.profile.get("rr_master")
    if not master_id:
        die("no master resume: set rr_master in profile.md (find it with `career resumes`)")
    master = api(ctx, "GET", f"/resumes/{master_id}")

    rid = state.get("id")
    if not rid:
        slug = slugify(f"{target['company']} - {target['role']}")  # the URL slug stays short; the name carries the full title
        for attempt in (slug, f"{slug}-{ctx.today:%Y%m%d}"):
            try:
                rid = api(ctx, "POST", f"/resumes/{master_id}/duplicate", {"name": doc_title(ctx, target), "slug": attempt, "tags": ["tailored"]})
                break
            except ApiError as e:
                if e.status == 400 and "SLUG" in e.body.upper():
                    continue
                raise
        if not rid:
            die("could not create a unique slug")
        state_file.write_text(json.dumps({"id": rid}))

    ops = content_ops(ctx, sel, master)
    if args.sync_design:
        ops = design_ops(master) + ops
    api(ctx, "PATCH", f"/resumes/{rid}", {"operations": ops})
    pdf = api(ctx, "GET", f"/resumes/{rid}/pdf?target=resume", raw=True)
    if not pdf.startswith(b"%PDF"):
        die(f"/pdf did not return a PDF (first bytes: {pdf[:40]!r}); export from the RR UI instead")
    titled = job / f"{file_safe(doc_title(ctx, target))}.pdf"
    previous = job / state["pdf"] if state.get("pdf") else None
    if previous and previous != titled and previous.exists():  # a role or company rename must not leave the old titled file behind
        previous.unlink()
    titled.write_bytes(pdf)
    (job / "resume.pdf").write_bytes(pdf)  # stable name for scripts and notes; the titled file is the one to send
    state_file.write_text(json.dumps({**state, "id": rid, "pdf": titled.name}))
    app_file = job / "app.json"
    if app_file.exists():  # a tracked application: keep the board pointing at this resume (idempotent)
        aid = json.loads(app_file.read_text()).get("id")
        if aid:
            api(ctx, "PUT", f"/applications/{aid}", {"resumeId": rid})
            print(f"linked to application {aid}")
    print(f"resume id: {rid} (Reactive Resume stores it: download the PDF from the link below, no other upload needed)\nopen in Reactive Resume: {rr_cfg(ctx)['url']}/builder/{rid}\npdf: {titled} ({len(pdf)} bytes)")
    return 0


# ---------------------------------------------------------------- saved cover letters (Reactive Resume > Cover Letters)
#
# Newer Reactive Resume keeps saved letters as their own documents (dashboard > Cover Letters), separate from the letter section
# inside a resume. They carry a `revision`: PUT and DELETE must send the revision they read (`expectedRevision`), so a save made
# in the browser is never silently overwritten. `cover` creates and updates the job's saved letter; `letters` reads and writes the list.

def html_text(s) -> str:
    """Plain text of a cover-letter HTML fragment: paragraph ends and <br> become line breaks."""
    s = re.sub(r"(?i)<br\s*/?>", "\n", s or "")
    s = re.sub(r"(?i)</p>\s*<p[^>]*>", "\n\n", s)
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def letter_sha(recipient, content) -> str:
    return hashlib.sha1(f"{recipient or ''}\n{content or ''}".encode()).hexdigest()[:16]


def letters_url(ctx: Ctx) -> str:
    return f"{rr_cfg(ctx)['url']}/dashboard/cover-letters"


def list_letters(ctx: Ctx, **filters) -> list:
    """Every saved letter matching the filters (search, resumeId, applicationId), fetched page by page."""
    rows, offset, size = [], 0, 50
    while True:
        q = urllib.parse.urlencode({**{k: v for k, v in filters.items() if v}, "limit": size, "offset": offset})
        page = api(ctx, "GET", f"/cover-letters?{q}")
        items = as_list(page)
        rows += items
        offset += len(items)
        total = page.get("total") if isinstance(page, dict) else None
        if not items or len(items) < size or (isinstance(total, int) and offset >= total):
            return rows


def job_ids(job: Path) -> tuple:
    """(resume id, application id) this job folder remembers."""
    def read(name):
        f = job / name
        return json.loads(f.read_text()).get("id") if f.exists() else None
    return read("rr.json"), read("app.json")


def find_job_letter(ctx: Ctx, job: Path, name: str = ""):
    """The saved letter that belongs to this job folder, or None. First the id kept in cover.json, then a lookup among the
    letters linked to the job's resume or tracker row (by name when there are several)."""
    f = job / "cover.json"
    cid = json.loads(f.read_text()).get("id") if f.exists() else None
    if cid:
        try:
            return api(ctx, "GET", f"/cover-letters/{cid}")
        except ApiError as e:
            if e.status != 404:
                raise                      # 404 means it was deleted in Reactive Resume: look for another one below
    found = {}
    for key, val in zip(("resumeId", "applicationId"), job_ids(job)):
        if val:
            for row in list_letters(ctx, **{key: val}):
                found[row["id"]] = row
    rows = list(found.values())
    pick = [r for r in rows if name and r.get("name") == name] or rows
    if len(pick) > 1:
        die("more than one saved cover letter is linked to this job; pass the id:\n" + "\n".join(f"  {r['id']} | {r.get('name')}" for r in pick))
    return api(ctx, "GET", f"/cover-letters/{pick[0]['id']}") if pick else None


def resolve_letter(ctx: Ctx, args) -> dict:
    """The one saved letter a `letters` command means: an id, or --job."""
    if getattr(args, "id", None):
        return api(ctx, "GET", f"/cover-letters/{args.id}")
    if getattr(args, "job", None):
        job = ctx.job_dir(args.job)
        found = find_job_letter(ctx, job)
        if not found:
            die(f"no saved cover letter for {job.name}; `career cover {job.name}` creates it")
        return found
    die("pass a letter id (see `career letters ls`) or --job <slug>")


def write_letter(ctx: Ctx, cur: dict, **fields) -> dict:
    """Update a saved letter using the revision just read. A revision conflict means it changed meanwhile: stop, do not retry blindly."""
    try:
        out = api(ctx, "PUT", f"/cover-letters/{cur['id']}", {"expectedRevision": cur["revision"], **fields})
    except ApiError as e:
        if e.status in (409, 412) or "revision" in e.body.lower():
            die(f"'{cur.get('name')}' was saved in Reactive Resume while this command ran (revision conflict). Nothing was overwritten; run it again.", 1)
        raise
    return out if isinstance(out, dict) and out.get("id") else api(ctx, "GET", f"/cover-letters/{cur['id']}")


def sync_saved_letter(ctx: Ctx, job: Path, letter: dict, rid: str, overwrite: bool = False) -> str:
    """Keep the job's saved letter in step with cover.yml: create it on the first run, update the same one afterwards. A letter that was
    edited in Reactive Resume since the last run is left alone unless `overwrite`. Returns the letter id ('' when the API is absent)."""
    name = doc_title(ctx, letter.get("target") or {}, "Cover Letter")[:100]
    recipient, content = letter_html(ctx, letter)
    sent = letter_sha(recipient, content)
    state_file = job / "cover.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    try:
        cur = find_job_letter(ctx, job, name)
    except ApiError as e:
        if e.status != 404:
            raise
        print("note: this Reactive Resume has no Cover Letters API (an older version), so the letter stays inside the resume only")
        return ""

    def remember(doc):
        state_file.write_text(json.dumps({"id": doc["id"], "sent": sent, "seen": letter_sha(doc.get("recipient"), doc.get("content"))}))

    if cur is None:
        body = {"name": name, "recipient": recipient, "content": content, "resumeId": rid}
        aid = job_ids(job)[1]
        if aid:
            body["applicationId"] = aid
        made = api(ctx, "POST", "/cover-letters", body)
        doc = made if isinstance(made, dict) and made.get("id") else api(ctx, "GET", f"/cover-letters/{made}")
        remember(doc)
        print(f"created cover letter '{doc.get('name', name)}' in Reactive Resume: {letters_url(ctx)}")
        return doc["id"]
    seen = letter_sha(cur.get("recipient"), cur.get("content"))
    mine = state.get("id") == cur["id"]                     # this job folder wrote the letter
    if mine and state.get("sent") == sent and (state.get("seen") == seen or not overwrite):
        if state.get("seen") == seen:
            print(f"cover letter '{cur.get('name')}' is already up to date in Reactive Resume")
        else:                                               # cover.yml has not changed, so there is nothing to push; keep the edits
            print(f"note: the saved cover letter '{cur.get('name')}' has edits made in Reactive Resume and was left as is; cover.pdf still comes from "
                  f"cover.yml. `career letters show --job {job.name}` reads the saved text; `career cover {job.name} --overwrite` replaces it")
        return cur["id"]
    if not (mine and state.get("seen") == seen) and not overwrite:
        die(f"the saved cover letter '{cur.get('name')}' was changed in Reactive Resume after the last `career cover` (or this job has no record of "
            f"writing it), and cover.yml would replace it. Nothing was overwritten. Read it with `career letters show --job {job.name}`, "
            f"or replace it with cover.yml via `career cover {job.name} --overwrite`.", 1)
    doc = write_letter(ctx, cur, recipient=recipient, content=content)   # the name is left alone: a rename in Reactive Resume is respected
    remember(doc)
    print(f"updated cover letter '{doc.get('name', cur.get('name'))}' in Reactive Resume: {letters_url(ctx)}")
    return doc["id"]


def cmd_letters(ctx: Ctx, args):
    act = args.action
    if act == "ls":
        filters = {"search": args.search, "resumeId": args.resume, "applicationId": args.application}
        if args.job:
            rid, aid = job_ids(ctx.job_dir(args.job))
            if not (rid or aid):
                die(f"{args.job} has no rr.json or app.json yet, so no letter can be linked to it")
            filters["resumeId"] = filters["resumeId"] or rid
        rows = list_letters(ctx, **filters)
        for r in rows:
            print(f"{r.get('id')} | {r.get('name')} | rev {r.get('revision')} | resume {r.get('sourceResumeId') or '-'} | "
                  f"application {r.get('sourceApplicationId') or '-'} | updated {r.get('updatedAt') or '-'}")
        print(f"{len(rows)} saved cover letter(s) ({letters_url(ctx)})")
        return 0
    if act == "import":
        doc = json.loads(Path(args.file).expanduser().read_text())
        never = [re.compile(r"\b" + re.escape(str(x)) + r"\b", re.I) for x in ctx.profile.get("never_claim") or []]
        issues = prose_issues([("recipient", html_text(doc.get("recipient"))), ("content", html_text(doc.get("content")))], never, first_person_ok=True)
        for lv, where, msg in issues:
            print(f"{lv} {where}: {msg}")
        if any(i[0] == "E" for i in issues):
            die("the letter breaks never_claim; fix it before importing (imported text is not checked against your atoms)", 1)
        made = api(ctx, "POST", "/cover-letters/import", {"document": doc})
        made = made if isinstance(made, dict) else {"id": made}
        print(f"imported '{made.get('name') or doc.get('name')}' as {made.get('id')}: {letters_url(ctx)}")
        return 0
    cur = resolve_letter(ctx, args)
    if act == "show":
        head = (f"{cur.get('name')} [{cur['id']}] | rev {cur.get('revision')} | resume {cur.get('sourceResumeId') or '-'} | "
                f"application {cur.get('sourceApplicationId') or '-'} | updated {cur.get('updatedAt') or '-'}")
        body = (f"{cur.get('recipient') or ''}\n{cur.get('content') or ''}" if args.html
                else f"{html_text(cur.get('recipient'))}\n\n{html_text(cur.get('content'))}")
        print(head + "\n\n" + body)
        if args.output:
            Path(args.output).expanduser().write_text(body + "\n")
            print(f"\nwrote {args.output}")
    elif act == "export":
        doc = api(ctx, "GET", f"/cover-letters/{cur['id']}/export")
        out = Path(args.output or f"{file_safe(cur.get('name') or cur['id'])}.cover-letter.json").expanduser()
        out.write_text(json.dumps(doc, indent=2))
        print(f"wrote {out}")
    elif act == "rename":
        doc = write_letter(ctx, cur, name=args.name[:100])
        print(f"renamed to '{doc.get('name', args.name)}'")
    elif act == "duplicate":
        made = api(ctx, "POST", f"/cover-letters/{cur['id']}/duplicate", {"name": args.name} if args.name else {})
        made = made if isinstance(made, dict) else {"id": made}
        print(f"duplicated '{cur.get('name')}' as {made.get('id')}" + (f" ('{made['name']}')" if made.get("name") else ""))
    elif act == "refresh-style":
        rid = args.resume or cur.get("sourceResumeId") or (job_ids(ctx.job_dir(args.job))[0] if args.job else None)
        if not rid:
            die("this letter is not linked to a resume: pass --resume <id> to copy that resume's style onto it")
        api(ctx, "POST", f"/cover-letters/{cur['id']}/refresh-style", {"expectedRevision": cur["revision"], "resumeId": rid})
        print(f"copied the style of resume {rid} onto '{cur.get('name')}'")
    elif act == "delete":
        if not args.yes:
            die(f"this permanently deletes '{cur.get('name')}' [{cur['id']}] from Reactive Resume; add --yes to confirm")
        api(ctx, "DELETE", f"/cover-letters/{cur['id']}", {"expectedRevision": cur["revision"]})
        if args.job:
            (ctx.job_dir(args.job) / "cover.json").unlink(missing_ok=True)
        print(f"deleted '{cur.get('name')}' [{cur['id']}]")
    return 0


def cmd_cover(ctx: Ctx, args):
    job = ctx.job_dir(args.job)
    src = job / "cover.yml"
    if not src.exists():
        die(f"{src} not found. Write it first (see workflows/cover.md).")
    letter = yaml.safe_load(src.read_text()) or {}
    issues = lint_letter(ctx, letter, job)
    for lv, where, msg in issues:
        print(f"{lv} {where}: {msg}")
    errors = sum(1 for i in issues if i[0] == "E")
    (job / "cover.md").write_text(letter_text(ctx, letter))
    print(f"{errors} error(s), {len(issues) - errors} warning(s); wrote {job / 'cover.md'}")
    if errors or args.dry:
        return 1 if errors else 0
    rid = (json.loads((job / "rr.json").read_text()) if (job / "rr.json").exists() else {}).get("id")
    if not rid:
        die("no tailored resume for this job yet: run `career push <slug>` first (the letter lives inside that resume)")
    if args.attach and not (job / "app.json").exists():
        die("--attach needs a tracker entry: run `career apply add --job <slug> ...` first")
    if not args.no_saved:   # first, so a letter edited in Reactive Resume stops the run before anything is written
        sync_saved_letter(ctx, job, letter, rid, args.overwrite)
    resume = api(ctx, "GET", f"/resumes/{rid}")
    secs = resume["data"].get("customSections") or []
    i = next((n for n, sec in enumerate(secs) if sec.get("type") == "cover-letter"), None)
    if i is None:
        master_id = (ctx.profile.get("rr_master") or "").strip()
        add = cover_section_ops(resume, api(ctx, "GET", f"/resumes/{master_id}") if master_id else None)
        api(ctx, "PATCH", f"/resumes/{rid}", {"operations": add})
        secs = secs + [add[0]["value"]]  # '/-' appends, so it is the last one
        i = len(secs) - 1
        print("added a cover-letter section to this resume")
    tpl = (secs[i].get("items") or [{}])[0]
    recipient, content = letter_html(ctx, letter)
    item = {**tpl, "id": tpl.get("id") or str(uuid.uuid4()), "hidden": False, "recipient": recipient, "content": content}
    ops = [{"op": "replace", "path": f"/customSections/{i}/items", "value": [item]}]
    if secs[i].get("hidden"):
        ops.append({"op": "replace", "path": f"/customSections/{i}/hidden", "value": False})
        print("note: the cover-letter section was hidden in the Master; unhid it. Check resume.pdf still has no letter page.")
    api(ctx, "PATCH", f"/resumes/{rid}", {"operations": ops})
    pdf = api(ctx, "GET", f"/resumes/{rid}/pdf?target=cover-letter", raw=True)
    if not pdf.startswith(b"%PDF"):
        die(f"/pdf?target=cover-letter did not return a PDF (first bytes: {pdf[:40]!r}); export it from the RR UI instead")
    (job / "cover.pdf").write_bytes(pdf)
    print(f"cover letter pdf: {job / 'cover.pdf'} ({len(pdf)} bytes)")
    if args.attach:
        attach_doc(ctx, json.loads((job / "app.json").read_text())["id"], "cover-letter", job / "cover.pdf")
        print("attached cover-letter to the tracker entry")
    return 0


def cmd_master_fill(ctx: Ctx, args):
    """Populate the Master with real content (so a template can be judged on it), a cover-letter section, and US page defaults."""
    rid = args.id or (ctx.profile.get("rr_master") or "").strip()
    if not rid:
        die("no master resume: run `career master` first")
    path, sel = load_selection(ctx, args.source)
    errs = [i for i in lint(ctx, sel) if i[0] == "E"]
    if errs:
        for lv, where, msg in errs:
            print(f"{lv} {where}: {msg}")
        die(f"lint errors in {path}; fix them first", 1)
    master = api(ctx, "GET", f"/resumes/{rid}")
    ops = content_ops(ctx, sel, master) + cover_section_ops(master, master) + us_defaults_ops(master)
    api(ctx, "PATCH", f"/resumes/{rid}", {"operations": ops})
    print(f"Master filled from {path.parent.name}: {len(sel.get('roles') or [])} roles, header, education, certifications, "
          f"{'a cover-letter section, ' if any(o['path'] == '/customSections/-' for o in ops) else ''}"
          f"{'US Letter and a tighter line height' if any(o['path'].startswith('/metadata') for o in ops) else 'page settings left as you set them'}")
    return 0


def cmd_master(ctx: Ctx, args):
    if args.fill:
        return cmd_master_fill(ctx, args)
    prof = ctx.root / "profile.md"
    if not prof.exists():
        die(f"{prof} not found. Run `career init` first.")
    rid = args.id
    current = (ctx.profile.get("rr_master") or "").strip()
    if args.if_unset and current:
        print(f"master already set ({current}); keeping it")
        return 0
    if not rid:
        rows = as_list(api(ctx, "GET", "/resumes"))
        cands = [r for r in rows if "master" in f"{r.get('name', '')} {r.get('slug', '')}".lower()]
        if not cands and args.create:
            # an empty resume (no sample data to leak into copies); restyle it in the builder whenever you like
            rid = api(ctx, "POST", "/resumes", {"name": "Master", "slug": "master", "tags": ["master"], "withSampleData": False})
            print("created an empty 'Master' resume with Reactive Resume's default template; pick another template in the builder any time")
        elif len(cands) != 1:
            print("could not pick the Master automatically. Resumes:" if rows else "no resumes found in Reactive Resume yet.")
            for r in rows:
                print(f"  {r.get('id')} | {r.get('name')}")
            print("Name your styled resume 'Master', run: career master <id>, or run: career master --create")
            return 1
        else:
            rid = cands[0]["id"]
            print(f"master: '{cands[0].get('name')}'")
    text, n = re.subn(r'(?m)^(rr_master:[ \t]*)("[^"]*"|[^\s#]*)', lambda m: f'{m.group(1)}"{rid}"', prof.read_text(), count=1)
    if not n:
        die("profile.md has no rr_master line")
    prof.write_text(text)
    print(f"rr_master set to {rid}")
    return 0


class CheckFail(Exception):
    pass


def cmd_check(ctx: Ctx, args):
    cfg = rr_cfg(ctx)
    print(f"url   {cfg['url']}  (from {cfg['src']})")
    failed = False

    def step(label, fn):
        nonlocal failed
        try:
            print(f"ok    {label}: {fn()}")
        except (ApiError, CheckFail, KeyError, ValueError) as e:
            failed = True
            print(f"FAIL  {label}: {e}")

    step("reachable", lambda: "/api/health " + json.dumps(api(ctx, "GET", "/api/health", auth=False, root=True))[:80])
    if not cfg["key"]:
        print(f"FAIL  api key: not set (put RR_API_KEY=... in {CONF}, chmod 600)")
        return 1
    step("api key", lambda: f"{len(as_list(api(ctx, 'GET', '/resumes')))} resumes visible")
    master = ctx.profile.get("rr_master")
    if not master:
        print(f"FAIL  master: rr_master not set in {ctx.root / 'profile.md'} (find the id with `career resumes`)")
        return 1

    def check_master():
        d = api(ctx, "GET", f"/resumes/{master}")
        sec = d["data"]["sections"]
        if not isinstance(d["data"].get("summary"), dict) or "experience" not in sec or "skills" not in sec:
            raise CheckFail("master is missing summary/experience/skills")
        has_cover = any(c.get("type") == "cover-letter" for c in d["data"].get("customSections") or [])
        return (f"'{d.get('name')}' has {len(sec['experience']['items'])} experience and {len(sec['skills']['items'])} skill items"
                + (" (locked)" if d.get("isLocked") else "")
                + ("; cover-letter section present" if has_cover else "; NO cover-letter section yet (`career master --fill` or `career cover` adds one)"))

    step("master", check_master)

    def check_letters():
        try:
            page = api(ctx, "GET", "/cover-letters?limit=1")
        except ApiError as e:
            if e.status == 404:
                return "not available on this Reactive Resume (older version); `career cover` keeps the letter inside the resume only"
            raise
        total = page.get("total") if isinstance(page, dict) else None
        return f"{total if isinstance(total, int) else len(as_list(page))} saved cover letter(s) visible ({letters_url(ctx)})"

    step("cover letters", check_letters)

    def check_mcp():
        init = mcp_rpc(ctx, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "career-check", "version": "1"}})
        tools = mcp_rpc(ctx, "tools/list").get("tools") or []
        if not tools:
            raise CheckFail("the MCP endpoint lists no tools")
        return f"{cfg['url']}/mcp accepts the key ({(init.get('serverInfo') or {}).get('name', '?')} {(init.get('serverInfo') or {}).get('version', '')}, {len(tools)} tools)"

    step("mcp endpoint", check_mcp)

    def check_mcp_registered():
        # Claude Code lists user-scope servers in ~/.claude.json; only the presence of the entry is read, never its contents.
        cfg_file = Path.home() / ".claude.json"
        entry = (json.loads(cfg_file.read_text()).get("mcpServers") or {}).get("reactive-resume") if cfg_file.exists() else None
        if not entry:
            raise CheckFail("not registered; run: claude mcp add-json -s user reactive-resume "
                            "'{\"type\":\"http\",\"url\":\"" + cfg["url"] + "/mcp\",\"headersHelper\":\"" + str(Path.home() / ".config/career/rr-mcp-headers.sh") + "\"}'")
        helper = entry.get("headersHelper")
        if helper and not os.access(helper, os.X_OK):
            raise CheckFail(f"headersHelper {helper} is missing or not executable (chmod 700 it)")
        if entry.get("url") != f"{cfg['url']}/mcp":
            raise CheckFail(f"registered for {entry.get('url')}, but rr_url is {cfg['url']}")
        return "registered in Claude Code (user scope)" + ("; key comes from rr.env via the header helper" if helper else "; static headers, not the helper")

    step("mcp registration", check_mcp_registered)
    return 1 if failed else 0


def cmd_pdf(ctx: Ctx, args):
    pdf = api(ctx, "GET", f"/resumes/{args.id}/pdf?target={args.target}", raw=True)
    if not pdf.startswith(b"%PDF"):
        die(f"not a PDF (first bytes: {pdf[:40]!r})")
    Path(args.output).write_bytes(pdf)
    print(f"wrote {args.output} ({len(pdf)} bytes)")
    return 0


# ---------------------------------------------------------------- applications

STAGE_ORDER = ["saved", "applied", "screening", "interview", "offer"]
# Fields the tracker accepts, by CLI flag. Everything the user or research learns about a posting belongs in one of them.
APP_FIELDS = (("location", "location"), ("salary", "salary"), ("source", "source"), ("url", "sourceUrl"))


def _norm(s) -> str:
    s = re.sub(r"[^a-z0-9 ]+", " ", str(s or "").lower().replace("&", " and "))
    s = re.sub(r"\bsr\b", "senior", s)
    s = re.sub(r"\bjr\b", "junior", s)
    s = re.sub(r"\bsystems?\b", "system", s)  # "Systems Administrator" vs "System Administrator"
    return " ".join(s.split())


def find_applications(ctx: Ctx, company: str, role: str = "") -> list:
    """Existing tracker rows for this company, best role match first. Company must match exactly (normalised);
    the role can differ in wording (Sr. vs Senior, a suffix like '- Remote'), so an unrelated role at the same
    company is listed last, not dropped: the caller decides."""
    import difflib
    cn, rn = _norm(company), _norm(role)
    hits = []
    for a in as_list(api(ctx, "GET", "/applications")):
        if _norm(a.get("company")) != cn:
            continue
        an = _norm(a.get("role"))
        score = 1.0 if an == rn else (0.9 if rn and (rn in an or an in rn) else difflib.SequenceMatcher(None, rn, an).ratio())
        hits.append((score, a))
    hits.sort(key=lambda t: -t[0])
    return [a for _, a in hits]


def resolve_app(ctx: Ctx, args) -> dict:
    """The one application a command means: explicit id, else the job folder's app.json, else company (+ role) lookup."""
    aid = getattr(args, "id", None)
    if not aid and getattr(args, "job", None):
        f = ctx.job_dir(args.job) / "app.json"
        if f.exists():
            aid = json.loads(f.read_text())["id"]
    if not aid and getattr(args, "company", None):
        hits = find_applications(ctx, args.company, getattr(args, "role", "") or "")
        good = [a for a in hits if _norm(a.get("role")) == _norm(getattr(args, "role", ""))
                or (getattr(args, "role", "") and _norm(args.role) in _norm(a.get("role")))
                or (getattr(args, "role", "") and _norm(a.get("role")) in _norm(args.role))]
        good = good or (hits if len(hits) == 1 and not getattr(args, "role", "") else [])
        if len(good) > 1:
            die("more than one matching application; pass the id:\n" + "\n".join(f"  {a['id']} | {a['role']} | {a.get('status')}" for a in good))
        if not good:
            die(f"no application for {args.company} / {getattr(args, 'role', '')}; `career apply add` creates one")
        aid = good[0]["id"]
    if not aid:
        die("no application id: pass an id, --job with an existing jobs/<slug>/app.json, or --company (and --role)")
    return api(ctx, "GET", f"/applications/{aid}") if not isinstance(aid, dict) else aid


def app_id(ctx: Ctx, args) -> str:
    if getattr(args, "id", None):
        return args.id
    r = resolve_app(ctx, args)
    return r["id"] if isinstance(r, dict) and r.get("id") else die("could not resolve the application")


def attach_doc(ctx: Ctx, aid: str, kind: str, file: Path):
    api(ctx, "POST", f"/applications/{aid}/documents/{kind}", multipart=("file", file.name, file.read_bytes()))


RESEARCH_HEAD = re.compile(r"(?m)^(?:== )?RESEARCH \d{4}-\d{2}-\d{2}")
RESEARCH_END = "== END RESEARCH =="


def merge_notes(old: str, new: str) -> str:
    """Existing notes are context, not truth. Hand-logged lines (Gmail, earlier scoring) stay, but a research block is
    a snapshot: a new one REPLACES the previous research block so stale pay, dates and contacts do not linger.
    Any other text is appended, and repeating identical text is a no-op."""
    old, new = (old or "").strip(), (new or "").strip()
    if not new:
        return old
    if RESEARCH_HEAD.match(new):
        m = RESEARCH_HEAD.search(old)
        if m:  # drop the old block: from its header to its end marker, or to the end of the notes if it has none
            end = old.find(RESEARCH_END, m.start())
            tail = old[end + len(RESEARCH_END):].strip() if end != -1 else ""
            old = (old[:m.start()].strip() + ("\n\n" + tail if tail else "")).strip()
        if RESEARCH_END not in new:
            new += "\n" + RESEARCH_END
    elif new in old:
        return old
    return f"{old}\n\n{new}" if old else new


def build_app_body(ctx: Ctx, args, existing: dict = None) -> dict:
    """Fields to send. Whatever the current request states wins over what the row holds (the row may be stale);
    fields the request does not mention are left alone."""
    body = {}
    for flag, key in APP_FIELDS:
        v = getattr(args, flag, None)
        if v and v != (existing or {}).get(key):
            body[key] = v
    notes = args.notes
    if getattr(args, "notes_file", None):
        notes = Path(args.notes_file).expanduser().read_text()
    if notes:
        body["notes"] = notes if getattr(args, "replace_notes", False) else merge_notes((existing or {}).get("notes"), notes)
    if getattr(args, "jd_file", None):
        body["jobDescription"] = Path(args.jd_file).expanduser().read_text()[:20000]
    elif args.job and (ctx.job_dir(args.job) / "jd.md").exists():
        body["jobDescription"] = (ctx.job_dir(args.job) / "jd.md").read_text()[:20000]
    if args.job and (ctx.job_dir(args.job) / "rr.json").exists():
        body["resumeId"] = json.loads((ctx.job_dir(args.job) / "rr.json").read_text())["id"]
    return body


def show_app(a: dict):
    for k in ("id", "company", "role", "status", "salary", "location", "source", "sourceUrl", "resumeId", "appliedAt", "followUpAt", "followUpNote"):
        if a.get(k):
            print(f"{k}: {a[k]}")
    print(f"notes: {a.get('notes') or ''}")
    print(f"jobDescription: {len(a.get('jobDescription') or '')} chars")
    for ev in a.get("activity") or []:
        print(f"  {ev.get('at', '')[:10]} {ev.get('type')} {ev.get('stage') or ev.get('text') or ''}"[:200])


def cmd_apply(ctx: Ctx, args):
    act = args.action
    if act == "add":
        hits = [] if args.force_new else find_applications(ctx, args.company, args.role)
        same = [a for a in hits if _norm(a.get("role")) == _norm(args.role) or _norm(args.role) in _norm(a.get("role")) or _norm(a.get("role")) in _norm(args.role)]
        if same:
            # One row per position. Bring the existing row up to date with this request; the stage only moves forward here (use `set` to go back).
            cur = api(ctx, "GET", f"/applications/{same[0]['id']}")
            body = build_app_body(ctx, args, cur)
            st, now = cur.get("status"), args.status
            if now and now != st and (now == "rejected" or (now in STAGE_ORDER and st in STAGE_ORDER and STAGE_ORDER.index(now) > STAGE_ORDER.index(st))):
                body["status"] = now
            if body:
                api(ctx, "PUT", f"/applications/{cur['id']}", body)
            print(f"existing application {cur['id']} ({cur.get('company')} | {cur.get('role')} | {cur.get('status')}): updated "
                  + (", ".join(body) or "nothing (already up to date)") + ". Not creating a new row.")
            if args.job:
                (ctx.job_dir(args.job) / "app.json").write_text(json.dumps({"id": cur["id"]}))
            return 0
        if hits:
            print("note: same company, different role already tracked: " + "; ".join(f"{a['role']} ({a.get('status')})" for a in hits), file=sys.stderr)
        body = {"company": args.company, "role": args.role, "status": args.status, **build_app_body(ctx, args)}
        new = api(ctx, "POST", "/applications", body)
        print(f"application id: {new}")
        if args.job:
            (ctx.job_dir(args.job) / "app.json").write_text(json.dumps({"id": new}))
    elif act == "set":
        cur = resolve_app(ctx, args)
        body = build_app_body(ctx, args, cur)
        if args.status:
            body["status"] = args.status
        if args.followup:
            body["followUpAt"] = f"{args.followup}T09:00:00Z"
        if args.followup_note:
            body["followUpNote"] = args.followup_note
        if args.archive:
            body["archived"] = True
        body.pop("resumeId", None) if not args.job else None
        if not body:
            die("nothing to change")
        api(ctx, "PUT", f"/applications/{cur['id']}", body)
        print(f"updated {cur.get('company')} | {cur.get('role')}: " + ", ".join(body))
    elif act == "find":
        for a in find_applications(ctx, args.company, args.role or ""):
            print(f"{a.get('id')} | {a.get('company')} | {a.get('role')} | {a.get('status')}")
    elif act == "show":
        show_app(resolve_app(ctx, args))
    elif act == "ls":
        for a in as_list(api(ctx, "GET", "/applications")):
            if not args.status or a.get("status") == args.status:
                print(f"{a.get('id')} | {a.get('company')} | {a.get('role')} | {a.get('status')}")
    elif act == "stats":
        s = api(ctx, "GET", "/applications/stats")
        print(f"total: {s.get('total')}")
        for row in s.get("byStage") or []:
            print(f"{row.get('status')}: {row.get('count')}")
    elif act == "doc":
        attach_doc(ctx, app_id(ctx, args), args.kind, Path(args.file).expanduser())
        print(f"attached {args.kind}")
    return 0


# ---------------------------------------------------------------- posting lookup

def _plain(h: str) -> str:
    import html as _h
    return " ".join(_h.unescape(_h.unescape(re.sub(r"<[^>]+>", " ", h or ""))).split())


def _pay_from_text(t: str) -> list:
    """Dollar ranges written into the body of a posting (pay-transparency paragraphs), with a little context.
    Amounts must look like salaries (>= $20k) and not be revenue/funding figures ($3M, $100M)."""
    out = []
    pat = r"\$\s?(\d[\d,\.]*)\s?([kKmMbB]\w*)?\s*(?:USD|CAD)?\s*(?:-|to|\u2013|\u2014|and)\s*\$?\s?(\d[\d,\.]*)\s?([kKmMbB]\w*)?(?:\s*(?:USD|CAD))?"
    for m in re.finditer(pat, t):
        def amount(n, suffix):
            try:
                v = float(n.replace(",", ""))
            except ValueError:
                return 0
            return v * 1000 if (suffix or "").lower() == "k" else v * 1e6 if (suffix or "").lower().startswith("m") else v * 1e9 if (suffix or "").lower().startswith("b") else v
        lo, hi = amount(m.group(1), m.group(2)), amount(m.group(3), m.group(4))
        if 20000 <= lo <= hi <= 2000000:
            out.append(t[max(0, m.start() - 60):m.end() + 40].strip())
    return out


def parse_posting(url: str, fetch=None) -> dict:
    """Public ATS posting APIs (no login): Ashby, Greenhouse, Lever. Returns title, location, published, pay, reports_to,
    text. `pay` is a list of sources, most reliable first; an empty list means the posting states no range."""
    fetch = fetch or (lambda u: json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": USER_AGENT}), timeout=30).read()))
    u = urllib.parse.urlparse(url)
    parts = [x for x in u.path.split("/") if x]
    q = urllib.parse.parse_qs(u.query)
    res = {"url": url, "ats": None, "title": None, "location": None, "published": None, "pay": [], "reports_to": None, "text": ""}
    if "ashbyhq.com" in u.netloc and len(parts) >= 2:
        res["ats"] = "ashby"
        board, jid = parts[0], parts[1]
        for j in fetch(f"https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true").get("jobs", []):
            if j.get("id") == jid:
                c = j.get("compensation") or {}
                if c.get("compensationTierSummary"):
                    res["pay"].append(f"structured: {c['compensationTierSummary']}")
                res.update(title=j.get("title"), location=j.get("location"), published=j.get("publishedAt"), text=_plain(j.get("descriptionHtml") or j.get("descriptionPlain")))
    elif "greenhouse.io" in u.netloc or "gh_jid" in q:
        res["ats"] = "greenhouse"
        jid = (q.get("gh_jid") or [parts[-1]])[0]
        # on a company's own domain the board token is usually ?for=, else the company name in the domain
        label = u.netloc.split(".")[-2] if u.netloc.count(".") else u.netloc
        boards = [parts[0]] if "greenhouse.io" in u.netloc else [*(q.get("for") or []), label]
        j = None
        for board in boards:
            try:
                j = fetch(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{jid}?pay_transparency=true")
                break
            except urllib.error.HTTPError:
                continue
        if j is None:
            die(f"Greenhouse job {jid} not found on board(s) {', '.join(boards)}: closed, or the board token differs. Try the job-boards.greenhouse.io URL.")
        for r in j.get("pay_input_ranges") or []:
            res["pay"].append(f"structured: {r.get('title') or ''} {r.get('min_cents', 0) // 100}-{r.get('max_cents', 0) // 100} {r.get('currency_type') or ''}".strip())
        html_body = j.get("content") or ""
        for m in re.finditer(r'<div class="title">([^<]*)</div><div class="pay-range"><span>([^<]*)</span><span class="divider">[^<]*</span><span>([^<]*)</span>', html_body):
            res["pay"].append(f"structured: {m.group(1).strip() or 'range'}: {m.group(2)} - {m.group(3)}")
        res.update(title=j.get("title"), location=(j.get("location") or {}).get("name"), published=j.get("first_published"), text=_plain(html_body))
    elif "lever.co" in u.netloc and len(parts) >= 2:
        res["ats"] = "lever"
        j = fetch(f"https://api.lever.co/v0/postings/{parts[0]}/{parts[1]}")
        sr = j.get("salaryRange")
        if sr:
            res["pay"].append(f"structured: {sr.get('min')}-{sr.get('max')} {sr.get('currency')} {sr.get('interval')}")
        cats = j.get("categories") or {}
        lists = " ".join(f"{l.get('text', '')} {_plain(l.get('content'))}" for l in j.get("lists") or [])
        made = j.get("createdAt")
        made = dt.datetime.fromtimestamp(made / 1000, dt.timezone.utc).strftime("%Y-%m-%d") if isinstance(made, (int, float)) else made
        res.update(title=j.get("text"), location=cats.get("location"), published=made,
                   text=" ".join([j.get("descriptionPlain") or "", lists, j.get("additionalPlain") or ""]).strip())
    else:
        die("unsupported posting URL (Ashby, Greenhouse and Lever are handled); read the page and use `career apply set` instead")
    res["pay"] += [f"in text: {x}" for x in _pay_from_text(res["text"])]
    m = re.search(r"(?:reports? (?:directly )?to|reporting to)\s+(?:the\s+)?([^.;]{3,70})", res["text"], re.I)
    res["reports_to"] = m.group(1).strip() if m else None
    return res


def cmd_posting(ctx: Ctx, args):
    r = parse_posting(args.url)
    if not r["title"]:
        die("that posting id is not on the board any more (closed or renumbered); check the URL")
    print(f"{r['ats']} | {r['title']} | {r['location']} | published {r['published']}")
    print("pay: " + (" || ".join(r["pay"]) if r["pay"] else "NOT STATED in the posting"))
    print(f"reports to: {r['reports_to'] or 'not stated'}")
    if args.out:
        Path(args.out).expanduser().write_text(r["text"])
        print(f"wrote {len(r['text'])} chars of description to {args.out}")
    else:
        print(r["text"][:args.chars])
    return 0


# ---------------------------------------------------------------- init / main

def cmd_init(ctx: Ctx, args):
    ctx.root.mkdir(parents=True, exist_ok=True)
    (ctx.root / "jobs").mkdir(exist_ok=True)
    for name in ("profile.md", "facts.md", "rules.md"):
        dst = ctx.root / name
        if dst.exists():
            print(f"kept existing {dst}")
        else:
            dst.write_text((ASSETS / name).read_text())
            print(f"created {dst}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="career", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", help="data folder (default: $CAREER_DATA or ~/Documents/Career Architect)")
    ap.add_argument("--today", help="override today's date (YYYY-MM-DD), for tests")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").set_defaults(fn=cmd_init)
    sub.add_parser("skills").set_defaults(fn=cmd_skills)
    p = sub.add_parser("match")
    p.add_argument("--req", required=True, help="tag[:must|nice[:min_years]],... e.g. okta:must:5,terraform:nice")
    p.set_defaults(fn=cmd_match)
    p = sub.add_parser("select")
    p.add_argument("--tags", required=True, help="comma-separated tags (same string as --req works)")
    p.add_argument("--cap", type=int, help="max atoms per role (default 6 recent, 3 older)")
    p.set_defaults(fn=cmd_select)
    p = sub.add_parser("build")
    p.add_argument("job", help="jobs/<slug> name or path to selection.yml")
    p.add_argument("--strict", action="store_true", help="treat warnings as errors")
    p.set_defaults(fn=cmd_build)
    p = sub.add_parser("push")
    p.add_argument("job")
    p.add_argument("--master", help="master resume id (default: rr_master in profile.md)")
    p.add_argument("--sync-design", action="store_true", help="also copy the Master's template, page, typography and layout onto this resume")
    p.set_defaults(fn=cmd_push)
    p = sub.add_parser("pdf")
    p.add_argument("id")
    p.add_argument("--target", choices=["resume", "cover-letter"], default="resume")
    p.add_argument("-o", "--output", default="out.pdf")
    p.set_defaults(fn=cmd_pdf)
    sub.add_parser("resumes").set_defaults(fn=cmd_resumes)
    sub.add_parser("check").set_defaults(fn=cmd_check)
    p = sub.add_parser("cover")
    p.add_argument("job", help="jobs/<slug> name or path")
    p.add_argument("--dry", action="store_true", help="lint and write cover.md only; no network")
    p.add_argument("--attach", action="store_true", help="attach cover.pdf to this job's tracker entry")
    p.add_argument("--overwrite", action="store_true", help="replace the saved letter even if it was edited in Reactive Resume after the last run")
    p.add_argument("--no-saved", action="store_true", help="only fill the resume's cover-letter section and save cover.pdf; leave Reactive Resume > Cover Letters alone")
    p.set_defaults(fn=cmd_cover)
    p = sub.add_parser("letters", help="the saved Cover Letters list in Reactive Resume: read, rename, duplicate, delete, import and export")
    p.set_defaults(fn=cmd_letters)
    lsub = p.add_subparsers(dest="action", required=True)

    def letter_ref(a):
        a.add_argument("id", nargs="?", help="letter id (see `letters ls`); or use --job")
        a.add_argument("--job", help="jobs/<slug>: that job's saved letter")
    a = lsub.add_parser("ls", help="list saved letters")
    a.add_argument("--search")
    a.add_argument("--resume", help="only letters linked to this resume id")
    a.add_argument("--application", help="only letters linked to this tracker row id")
    a.add_argument("--job", help="only the letters linked to this job's resume")
    a = lsub.add_parser("show", help="print a letter as text (or HTML)")
    letter_ref(a)
    a.add_argument("--html", action="store_true", help="print the stored HTML instead of plain text")
    a.add_argument("-o", "--output", help="also write the letter text to this file")
    a = lsub.add_parser("export", help="save a letter as a Reactive Resume cover-letter JSON document")
    letter_ref(a)
    a.add_argument("-o", "--output")
    a = lsub.add_parser("import", help="create a letter from an exported JSON document (checked against never_claim)")
    a.add_argument("file")
    a = lsub.add_parser("rename")
    letter_ref(a)
    a.add_argument("--name", required=True)
    a = lsub.add_parser("duplicate")
    letter_ref(a)
    a.add_argument("--name", help="name of the copy")
    a = lsub.add_parser("refresh-style", help="copy the linked resume's template and design onto the letter")
    letter_ref(a)
    a.add_argument("--resume", help="resume whose style to copy (default: the one the letter is linked to)")
    a = lsub.add_parser("delete", help="permanently delete a saved letter")
    letter_ref(a)
    a.add_argument("--yes", action="store_true", help="confirm the deletion")
    p = sub.add_parser("master")
    p.add_argument("id", nargs="?", help="resume id; omit to auto-detect a resume named 'Master'")
    p.add_argument("--if-unset", action="store_true", help="do nothing when rr_master is already set")
    p.add_argument("--create", action="store_true", help="create an empty 'Master' resume when none exists")
    p.add_argument("--fill", action="store_true", help="fill the Master with a job's selection (default: general), a cover-letter section and US Letter defaults")
    p.add_argument("--from", dest="source", default="general", help="job whose selection fills the Master (default: general)")
    p.set_defaults(fn=cmd_master)
    p = sub.add_parser("posting", help="fetch a public Ashby/Greenhouse/Lever posting: pay, reports-to, description")
    p.add_argument("url")
    p.add_argument("--out", help="write the description text here (e.g. jobs/<slug>/jd.md)")
    p.add_argument("--chars", type=int, default=1500, help="how much description to print when --out is not given")
    p.set_defaults(fn=cmd_posting)
    p = sub.add_parser("apply")
    p.set_defaults(fn=cmd_apply)
    asub = p.add_subparsers(dest="action", required=True)
    st = ["saved", "applied", "screening", "interview", "offer", "rejected"]
    def app_fields(a):
        for f in ("location", "salary", "source", "url", "notes"):
            a.add_argument(f"--{f}")
        a.add_argument("--notes-file", help="read notes from a file (long research blocks)")
        a.add_argument("--jd-file", help="store this file as the job description")
        a.add_argument("--replace-notes", action="store_true", help="overwrite the notes instead of appending")
    a = asub.add_parser("add", help="creates a row, or updates the existing one for the same company + role")
    a.add_argument("--company", required=True)
    a.add_argument("--role", required=True)
    a.add_argument("--status", choices=st, default="saved")
    a.add_argument("--job", help="jobs/<slug>: links its RR resume and jd.md")
    a.add_argument("--force-new", action="store_true", help="skip the existing-row check")
    app_fields(a)
    a = asub.add_parser("set")
    a.add_argument("id", nargs="?")
    a.add_argument("--job")
    a.add_argument("--company", help="find the row by company (+ --role) instead of an id")
    a.add_argument("--role")
    a.add_argument("--status", choices=st)
    a.add_argument("--followup", help="YYYY-MM-DD")
    a.add_argument("--followup-note")
    a.add_argument("--archive", action="store_true")
    app_fields(a)
    a = asub.add_parser("find")
    a.add_argument("--company", required=True)
    a.add_argument("--role")
    a = asub.add_parser("show")
    a.add_argument("id", nargs="?")
    a.add_argument("--job")
    a.add_argument("--company")
    a.add_argument("--role")
    a = asub.add_parser("ls")
    a.add_argument("--status", choices=st)
    asub.add_parser("stats")
    a = asub.add_parser("doc")
    a.add_argument("kind", choices=["resume", "cover-letter"])
    a.add_argument("file")
    a.add_argument("id", nargs="?")
    a.add_argument("--job")
    args = ap.parse_args(argv)
    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    ctx = Ctx(args.data, today)
    try:
        return args.fn(ctx, args) or 0
    except ApiError as e:
        die(str(e))


if __name__ == "__main__":
    sys.exit(main())
