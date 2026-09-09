# Website discovery and QR

Read this reference when onboarding has a church website, or when the pastor
wants brand or QR help. It is a supporting procedure for the general
onboarding skill, not a separate interview.

## Bounded discovery

Inspect the homepage first. Follow only relevant links such as About, Worship,
Contact, Staff, Newcomers, Give, and Events. Do not crawl the whole site by
default.

Collect only public information that affects onboarding:

- formal and public church names;
- tradition or denomination when clearly stated;
- address, city, service times, phone, email, and website;
- public clergy, staff, musicians, and ministry contacts;
- newcomer, contact, volunteer, newsletter, and giving links;
- logo and favicon candidates;
- theme colors and repeated brand-like colors; and
- page or CSS evidence supporting each finding.

Store the bounded result in the private church folder after it exists. Keep
source URL, extraction date, and confidence with each value. Label every item
as **found on the website**, **supplied by the pastor**, or **proposed from a
visual sample**.

Return four plain-language groups:

1. **What I found**
2. **Brand preview**
3. **Possible conflicts**
4. **Still unknown**

Website candidates are not standing configuration. Bundle the supported
identity values, folder proposal, and any conflicts into one confirmation. Do
not ask the pastor to confirm each website field in a separate turn. If pages
disagree, show both sources and ask which value is correct. Do not silently
choose the website or the pastor when the conflict matters.

## Brand candidates

Inspect header logo images or SVG marks, favicon and Apple touch icons, the
`theme-color` metadata value, CSS custom properties, and a small palette from
the strongest logo candidate. JavaScript-heavy sites or page builders may
need a bounded rendered inspection.

Show the candidate and its source page. Say whether it appears suitable for
print. If it is small or blurry, offer three choices: keep the original,
create an optional larger local copy, or use neutral defaults. Never replace
the original silently. Copied assets belong in the private church folder, not
this repository.

When the church selects a logo, save the image inside its private `brand/`
folder and store a church-relative path in `brand.json` under `logo.mark` or
`logo.banner`. A website URL alone is discovery evidence, not a print asset.
Keep its source URL in the onboarding notes. Both Classic and Modern use the available local church logo on the front
cover, including when only a mark or only a banner was supplied.

## QR destinations after the first useful result

Record likely destinations during discovery without turning them into new
questions. Surface QR setup only when the pastor requests it or when a QR code
in the supplied bulletin must be replaced for the next requested proof:

> I can create the QR images for you. I’ll look for likely connection and
> giving pages on your website, show you the destinations, and create the
> images after you confirm them.

Ask whether the church wants a connect QR code, a giving QR code, both, or
neither. Show candidates separately. A Newcomers, Contact, Volunteer, or Give
page is only a candidate until the pastor approves it. Do not guess that the
homepage is the connect destination or select a giving provider based only on
appearance.

Before creating an image, read back the confirmed URL, action, proposed
heading and label, and private destination path. Show this standard copy
before saving it:

```text
Heading: Connect and Give
Connect label: Connect with us
Give label: Support our ministry
```

Supporting sentences are optional custom copy. A generated QR image is a
local asset. It does not administer the linked website, giving provider, or
account.

Run the helper once as a plan, then apply only after the pastor confirms the
read-back:

```bash
<runtime.python> <skill-dir>/scripts/qr_setup.py \
  --church-folder <church-folder> --kind <connect-or-give> \
  --url <confirmed-url> [--image <existing-image>]

<runtime.python> <skill-dir>/scripts/qr_setup.py \
  --church-folder <church-folder> --kind <connect-or-give> \
  --url <confirmed-url> [--image <existing-image>] --apply
```

Save confirmed URLs, image paths, and final copy in `brand.json` under the QR
fields. Unselected actions stay blank and are reported as not configured. If
QR generation is unavailable, save the confirmed URL and mark the image as
pending.
