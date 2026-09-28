// Applies deploy/jobs-vmcp.json to the Jobs virtual MCP server in Obot. Paste into the browser console on your Obot address
// while signed in as an Obot administrator. It only calls your own Obot's API (same origin) and one GET for the spec.
//
//   1. Create the vMCP once in the Obot UI (vMCPs, Create): name `Jobs`, and add the four servers as components named exactly
//      Career Architect, Reactive Resume, Google Drive, Google Docs (the component name becomes the tool prefix). Connect each.
//   2. Run this script. It sets the description, enables the tools in the spec, disables every other tool, and writes the
//      descriptions. It prints what it changed. Run it again after any change to the spec; a second run changes nothing.
//   3. Open the vMCP's Inspector tab and check the tool list.
//
// A tool that exists on a server but is in neither list of the spec (a server update added it) is DISABLED and reported, so a new
// capability never appears in the Jobs server without a decision. Profiles (who may connect) are not touched.
//
// Read it before you run it. It uses Obot's own UI API, which can change between Obot versions (written against Obot community `latest`, 2026-09).
(async () => {
  const SPEC_URL = window.JOBS_SPEC_URL || "https://raw.githubusercontent.com/ConniptionFit/career-architect/main/deploy/jobs-vmcp.json";
  const MARK = " Jobs skill:";           // everything from here on in a description is ours; a rerun replaces it
  const spec = window.JOBS_SPEC || await (await fetch(SPEC_URL)).json();
  const api = async (path, opts = {}) => {
    const r = await fetch(path, { credentials: "include", headers: { "content-type": "application/json" }, ...opts });
    if (!r.ok) throw new Error(`${opts.method || "GET"} ${path}: ${r.status} ${(await r.text()).slice(0, 300)}`);
    return r.json();
  };
  const list = (await api("/api/vmcps")).items.filter((v) => v.displayName === spec.name);
  if (list.length !== 1) throw new Error(`expected exactly one vMCP named ${spec.name}, found ${list.length}. Create it first (see the header of this script).`);
  const v = await api(`/api/vmcps/${list[0].id}`);
  const before = JSON.stringify(v);
  const report = [];

  for (const src of spec.sources) {
    const comp = v.components.find((c) => c.name === src.component);
    if (!comp) throw new Error(`the vMCP has no component named ${src.component}. Add it in the Obot UI first.`);
    const have = new Map((comp.toolOverrides || []).map((t) => [t.name, t]));
    const known = new Set([...src.enabled, ...src.disabled]);
    for (const name of have.keys()) if (!known.has(name)) { report.push(`${src.component}: new tool ${name} is not in the spec; disabled until you decide`); }
    const names = [...new Set([...src.enabled, ...src.disabled, ...have.keys()])];
    comp.toolOverrides = names.map((name) => {
      const old = have.get(name) || {};
      const on = src.enabled.includes(name);
      let description = (src.descriptions || {})[name];
      if (description === undefined) {
        description = (old.description || "").split(MARK)[0];
        const extra = (src.append_to_description || {})[name];
        if (on && extra) description += extra;
      }
      const t = { name, description, enabled: on };
      if (!description) delete t.description;
      if (!on) delete t.enabled;                     // Obot omits false
      return t;
    });
    if (have.size) for (const name of src.enabled) if (!have.has(name)) report.push(`${src.component}: spec enables ${name}, which the server does not list (yet)`);
  }
  v.description = spec.description;
  if (JSON.stringify(v) === before) { console.log("Jobs vMCP already matches the spec.", report); return; }
  const body = { displayName: v.displayName, description: v.description, components: v.components, profiles: v.profiles };
  window.__jobsVmcpBackup = JSON.parse(before);       // in this tab only: PUT it back to undo
  const out = await api(`/api/vmcps/${v.id}`, { method: "PUT", body: JSON.stringify(body) });
  const counts = out.components.map((c) => `${c.name}: ${(c.toolOverrides || []).filter((t) => t.enabled).length} of ${(c.toolOverrides || []).length} tools on`);
  console.log("Jobs vMCP updated.\n" + counts.join("\n") + (report.length ? "\nCheck:\n" + report.join("\n") : ""));
})();
