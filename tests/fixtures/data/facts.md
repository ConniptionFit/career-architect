# Facts
```yaml
aliases:
  okta: [idp, sso]
credentials:
  - {name: "Okta Certified Professional", issuer: Okta, year: 2023, tags: [okta-cert]}
education:
  - {school: "Northwind Tech", degree: AAS, area: "IT Support", location: "Duluth, MN", tags: [networking]}

roles:
  - id: northwind-se
    title: IT Systems Engineer
    org: Northwind Logistics
    span: 2021-03..present
    location: Remote
    context: "~1,800 endpoints, 3-person team"
    atoms:
      - {id: nw-01, say: "Moved ~1,800 Macs from Kandji to Jamf with no reimaging", tags: [mdm, jamf, macos, migration], depth: owned, nums: {devices: 1800}, status: verified, note: "Write 1,800 as about 1,800, never just over 1,000."}
      - {id: nw-02, say: "Built Okta lifecycle automation for joiners, movers and leavers across 12 SaaS apps", tags: [okta, automation, iam, saas], depth: owned, nums: {apps: 12}, status: verified}
      - {id: nw-03, say: "Cut new-hire laptop setup from two days to a few hours", tags: [onboarding, mdm], depth: used, status: needs_number}
      - {id: nw-04, say: "Handled tier 3 escalations for Google Workspace admin issues", tags: [google-workspace, support], depth: used, status: verified}
      - {id: nw-05, say: "Wrote a Python script to reconcile Okta users against HR exports", tags: [python, okta, automation], depth: used, span: 2023-01..2023-06, status: verified}
      - {id: nw-07, say: "Onboarded a salon chain as a support client", tags: [salon-industry], depth: used, status: verified, only_for: [salon-industry, beauty]}
      - {id: nw-06, say: "Led the SOC 2 evidence collection", tags: [soc2], depth: owned, status: unconfirmed}
  - id: contoso-helpdesk
    title: Help Desk Analyst
    framings: ["IT Support Engineer"]
    org: Contoso Retail
    span: 2018-06..2021-02
    atoms:
      - {id: co-01, say: "Supported about 400 users across four offices, Windows and macOS", tags: [support, windows, macos], depth: used, nums: {users: 400}, status: verified}
      - {id: co-02, say: "Built the first Intune enrollment for new laptops", tags: [intune, mdm, windows], depth: used, status: verified}
      - {id: co-04, say: "Evaluated Jamf and Workspace ONE in a proof of concept", tags: [jamf, workspace-one], depth: exposure, status: verified}
      - {id: co-03, say: "Ran Active Directory account and group administration", tags: [active-directory, iam], depth: used, status: verified}
  - id: side-consulting
    title: IT Consultant (part-time)
    org: Freelance
    span: 2019-01..2020-12
    atoms:
      - {id: fr-01, say: "Set up Google Workspace for three small clients", tags: [google-workspace, support], depth: used, status: verified}
log: []
```
