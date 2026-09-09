# Private service orders

This folder is for this church's approved order files. Do not put licensed
liturgy text in Handbuilt Church Labs or in a public example.

Each configured entry in `../profile.yaml` names an exact `name`, its matching
`base_service_plan`, a church-relative `order_file`, and a confirmation policy.
An order file may contain:

```yaml
extends: another-configured-variant-id
replace:
  - unit: stable-plan-anchor
    with: [church-owned-unit]
insert:
  - after: another-plan-anchor
    units: [another-church-owned-unit]
files:
  church-owned-unit: worship/liturgy/church-owned-unit.md
```

The resolver follows `extends` through configured variants, applies the base
first and the selected child last, and keeps every path inside this church
folder. `files` maps logical units to existing, licensed, church-relative text
files and is merged into the resolved `liturgy.files` map for staging. Weekly
input must confirm `service.variant` before the order is used.
