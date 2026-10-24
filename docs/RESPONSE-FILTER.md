# Response filter (Obot + Redpanda Connect)

Optional. An Obot **filter** can send every MCP `tools/call` response through a small adapter and a Redpanda Connect pipeline before it reaches the client, so that fields nobody asked for can be dropped and fewer tokens reach the model. Nothing in this repository needs it, and the skill behaves the same with or without it. This page is the administrator's reference for running it safely.

## The policy

1. **Never remove requested content.** No truncation, no list caps, no "first N characters". A field is removed only if it is not part of what the tool call asked for, and only by a rule someone wrote down and reviewed.
2. **Fail open.** Any error, timeout, oversized body or failed safety check returns the original response unchanged.
3. **The Jobs reads and checks are exempt.** `career_architect__*` (guide, info, match, build_index, lint, patch, normalize, posting), `google_docs__*` reads and writes, and `google_drive__read_file` skip the pipeline: those tools need whole documents, and the atoms check is only as good as its input.
4. **No content in logs.** Tool names, byte counts and key names only.

An earlier version of the pipeline cut text over 8,000 characters and capped lists at 20 items, with no exemptions. That broke policy 1 and was switched off on 2026-10-23. Do not bring it back.

## How it fits

```
client -> Obot -> MCP server
                    |
          tools/call response
                    |
   Obot filter "Redpanda Response Trimmer"   (selector tools/call, may modify)
                    |
   obot-filter-adapter  :8080/mcp  tool filter_response
     - exempt tool?          -> return unchanged
     - shadow mode           -> log what a rule would remove, return unchanged
     - enforce mode          -> ask the pipeline, then a guard proves only
                                configured keys were removed, else unchanged
                    |
   obot-response-filter  (Redpanda Connect, POST /filter)
```

| Part | What it is | Notes |
|---|---|---|
| Obot filter | Obot admin, MCP Servers, Filters | Selector `tools/call`; pick the servers it applies to; "allow modification" must be on for enforce mode to have any effect |
| `obot-filter-adapter` | A Node MCP server (`server.cjs`) exposing `filter_response` at `/mcp` | Modes `shadow` (default) and `enforce`; 10 s timeout; 32 MB body cap; a fixed list of protected keys (`text`, `content`, `items`, `files`, `id`, `name`, `url` and others) can never be removed; `/status` returns counters (calls, exempt, pass-through, would-trim, trimmed, errors, guard rejections) |
| `obot-response-filter` | Redpanda Connect (Apache 2.0, the `redpandadata/connect` image) with `connect.yaml` | Stateless HTTP server pipeline. **It needs no Redpanda broker**: do not run one for this |

The adapter and pipeline are deployment files, kept next to Obot's compose file (`<compose-dir>/obot/filter/`), not in this repository. Keep them under version control on the host, and back them up before every change.

## Running it

**Add the filter in Obot.** A filter created from a catalog entry that uses a fixed URL cannot be saved in the community `latest` UI (2026-10): the form drops `fixedURL` and then fails validation without a message. Use + Add new filter, *Create custom*:

- Runtime *Remote*, URL `http://obot-filter-adapter:8080/mcp`, tool `filter_response`.
- Selector `tools/call`.
- MCP servers: start with one low-risk server, then widen. Apply it only to servers whose responses you have rules for; every server it covers pays two extra hops per call.
- Allow modification: off while in shadow mode (nothing is modified anyway), on only when you switch the adapter to enforce.

**Never save a filter with an empty URL.** Obot launches each filter as a system MCP server; an empty or unreachable one crash-loops, and while it does **every MCP call through Obot fails**, the Jobs connector included, with:

```
failed to run hook ... failed to launch system MCP server ... container repeatedly crashed
```

Fix: delete or disable the filter in Obot, then make one call (`career_architect__info`) to confirm.

**Shadow first.** Leave the adapter in `shadow` for at least a day of real traffic. Then read `/status` and the adapter's log for `would-trim` lines: they name the tool and the keys a rule would remove, with sizes. Only write a rule for a key that is plainly not part of what the caller asked for (transport metadata, duplicated envelopes), never for a key that carries the answer.

**Enforce.** Set the adapter's mode to `enforce` in its compose file, recreate the container, turn on "allow modification" in the Obot filter, and make one call to each covered tool. Check `/status`: `guard rejections` and `errors` should stay at 0. A non-zero guard count means a rule touched more than its keys and the original was returned; fix the rule.

**Turn it off.** Delete or disable the filter in Obot. Responses go straight to the client again; nothing else depends on the adapter.

## Verify

```
docker logs --tail 50 obot-filter-adapter         # tool names, sizes, key names only
docker logs --tail 50 obot-response-filter        # no errors
docker run --rm --network <obot-network> curlimages/curl -s http://obot-filter-adapter:8080/status
docker run --rm --network <obot-network> curlimages/curl -s http://obot-response-filter:<port>/ready
```
`<port>` is the pipeline's HTTP port (`http.address` in `connect.yaml`; Redpanda Connect's default is 4195).

Then call `career_architect__info` from a client: it must succeed, and the adapter should count it as exempt.

## Known limits

- The adapter pairs a response with its tool by JSON-RPC id. Two concurrent sessions can use the same id, so a response could be matched to the wrong tool's exemption. Harmless in shadow mode; key the pairing on session and id before enforcing for a larger group.
- The filter adds two hook round trips to every covered call. With no trim rules it saves nothing, so either write rules or leave the filter off.
- Redpanda Connect's HTTP endpoint has no authentication of its own. Do not publish its port; only the adapter needs to reach it, over the Docker network.
