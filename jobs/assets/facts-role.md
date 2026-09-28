# Document `facts - <role-id>`: one role and its atoms. Name the document after the role's id, e.g. `facts - acme-se`.
# Plain YAML (a fenced yaml block is accepted too).
#
# An atom is one accomplishment. Resumes, scores and interview stories are derived from atoms, so a correction made here reaches every future document.
# After any change the assistant validates all fragments together and regenerates the `skills` index.

roles:
  - id: acme-se                    # short, stable, kebab-case; the same as the document name
    title: IT Systems Engineer     # the title actually held
    framings: ["Senior IT Systems Engineer"]   # optional: other titles a resume may use for this role
    org: Acme Corp
    span: 2021-03..present         # YYYY-MM..YYYY-MM or ..present
    location: Remote               # optional
    context: "~1,800 endpoints, 3-person team"   # optional, at most 25 words; figures here may be cited in bullets
    atoms:
      - id: acme-01                # unique across every fragment: a short role prefix and a number
        say: "Moved ~1,800 Macs from one MDM to another with no reimaging"   # YOUR plain wording; bullets derive only from this
        tags: [mdm, jamf, macos, migration]
        depth: owned               # exposure | used | owned | designed
        nums: {devices: 1800}      # optional; every figure a bullet may cite must appear here or in `say`
        status: verified           # verified | needs_number | unconfirmed | excluded
        span: 2022-01..2022-06     # optional: when this skill was actually used, if narrower than the role
        no_years: true             # optional: when it started is not known (e.g. AI tools inside an older role), so it adds no years
        note: "caveat the assistant must respect, shown with the atom at selection time"
        only_for: [salon-industry] # optional: the atom is offered only when a requested tag matches
        star: {s: "", t: "", a: "", r: ""}   # optional: only what you supplied, for interview prep
