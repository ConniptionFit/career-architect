# Document `facts - shared`: the parts of your history that belong to no single role.
# Plain YAML (a fenced yaml block is accepted too). Every accomplishment lives in a `facts - <role-id>` document, not here.

# aliases: synonyms that count as the same skill. Key = the tag you use.
aliases: {}
#  okta: [idp, sso]
#  jamf: [jamf-pro]
# related: tools whose hands-on evidence is adjacent to a skill you do not have yourself. Scoring shows it as "adjacent",
# never as met, and nothing is claimed from it. Common peer tools (Jamf/Kandji/Intune, Okta/Entra, ...) are built in.
related: {}
#  zero-trust: [conditional-access, device-trust]

# credentials: certifications and licences (used for scoring and printed on resumes).
# `name` is the FULL official name, one line each, never abbreviated or merged, so applicant systems parse it.
credentials: []
#  - {name: "Okta Certified Professional", issuer: Okta, year: 2023, tags: [okta]}

education: []
#  - {school: "Example University", degree: AAS, area: "Network Administration", location: "City, ST", tags: [networking]}

# log: one dated line per change, newest first
log: []
#  - "2026-09-20: created from a resume the person supplied"
