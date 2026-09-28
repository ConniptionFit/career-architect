# Facts (source of truth)

Every accomplishment is one atom. Resumes, scores and interview stories are all derived from these records, so a
correction made here reaches every future document. After editing, run `career skills`.

```yaml
# aliases: synonyms that should count as the same skill. Key = the tag you use.
aliases: {}
#  okta: [idp, sso]
#  jamf: [jamf-pro]

# credentials: certifications and degrees (used for scoring and printed on resumes). `name` is the FULL official name, one line each, never abbreviated or merged, so HRIS parsers scrape it
credentials: []
#  - {name: "Okta Certified Professional", issuer: Okta, year: 2023, tags: [okta]}

education: []
#  - {school: "Example University", degree: AAS, area: "Network Administration", location: "City, ST", tags: [networking]}

roles: []
# Most recent first.
#  - id: acme-se                    # short, stable, kebab-case
#    title: IT Systems Engineer     # the title actually held
#    framings: ["Senior IT Systems Engineer"]   # optional: other titles a resume may use for this role
#    org: Acme Corp
#    span: 2021-03..present         # YYYY-MM..YYYY-MM or ..present
#    location: Remote               # optional
#    context: "~1,800 endpoints, 3-person team"   # optional, <= 25 words; figures here may be cited in bullets
#    atoms:
#      - id: acme-01                # unique across the whole file
#        say: "Moved ~1,800 Macs from Kandji to Jamf with no reimaging"   # YOUR plain wording; bullets derive only from this
#        tags: [mdm, jamf, macos, migration]
#        depth: owned               # exposure | used | owned | designed
#        nums: {devices: 1800}      # optional; every figure a bullet may cite must appear here or in say
#        status: verified           # verified | needs_number | unconfirmed | excluded
#        span: 2022-01..2022-06     # optional: when this skill was actually used, if narrower than the role
#        no_years: true             # optional: when it started is not known (e.g. AI tools inside an older role), so it adds no years
#        note: "caveat the agent must respect, shown with the atom at selection time"
#        only_for: [salon-industry]    # optional: atom is offered only when a requested tag matches
#        star: {s: "", t: "", a: "", r: ""}   # optional: only what you supplied, for interview prep

# log: one dated line per change, newest first
log: []
#  - "2026-09-20: created from the old profile"
```
