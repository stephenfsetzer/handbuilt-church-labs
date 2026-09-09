# Standard Sunday worship text

Use the bundled library before a web request or a question about a source.
The pastor chooses the church's practice. The agent locates standard text.
Do not ask a pastor to find a verified public URL for an ordinary BCP choice.

## Episcopal, English 1979 Book of Common Prayer, Rite II

The tradition catalog resolves Eucharistic Prayers A through D, both Lord's
Prayer forms, and Prayers of the People I through VI to bundled text. Save the
selected name in the worship profile. Leave its private source field blank
unless the church deliberately uses a local adaptation. Standard text does
not require copying into each private church folder or creating a private
source record. Full and congregation-only Eucharistic prayer presentation
follow the saved print preference.

### Identify an unnamed Prayers of the People form

Use this index to choose a candidate, then compare its actual bundled text
with the printed petitions and responses. Do not declare a prayer custom
after checking only one or two forms. Local names or added petitions may be
additions to a standard form. Keep those additions private and explicit.

| Form | Recognizable opening | Bundled file in `renderer/liturgy/` |
| --- | --- | --- |
| I | With all our heart and with all our mind | `prayers-of-the-people-i.md` |
| II | I ask your prayers for God's people throughout the world | `prayers-of-the-people-ii.md` |
| III | Father, we pray for your holy Catholic Church | `prayers-of-the-people.md` |
| IV | Let us pray for the Church and for the world; Grant, Almighty God | `prayers-of-the-people-iv.md` |
| V | In peace, let us pray to the Lord | `prayers-of-the-people-v.md` |
| VI | In peace, we pray to you, Lord God | `prayers-of-the-people-vi.md` |

Form III intentionally uses the unsuffixed filename. Ask the pastor about
unmatched wording only after inspecting the matching candidate and identifying
the actual difference. Standard Form III does not require a private source.

These are BCP words, including its original pronouns and titles. Do not label
an inclusive adaptation as unchanged BCP text. An intentional church version
belongs in the private church folder with its own verified source record.
When an older private copy is unverified, explain that the standard BCP text
is available and establish whether the church wants that text or its local
version. Do not silently discard a private override.

After identifying the appointed occasion and psalm, use the managed runtime:

```bash
<runtime.python> <skill-dir>/scripts/sunday_library.py list collects
<runtime.python> <skill-dir>/scripts/sunday_library.py list prefaces
<runtime.python> <skill-dir>/scripts/sunday_library.py get psalms 23 --verses 1-6 --psalm-format responsive_half_verse
```

For a collect or preface, use `get collects <id>` or `get prefaces <id>` with
an identifier returned by `list`. Copy the returned text and source record
into the weekly input. The psalm result already supplies numbered, structured
verses and source metadata for `readings.psalm`. Pass the church's confirmed
response pattern; never change its pattern just because the example uses
half verses. Use the appointed verse selection, including nonconsecutive
ranges when called for.

The library supplies exact text, not calendar decisions. Verify the service
date, occasion, lectionary track, appointed passages, and any permitted choices
through the existing reading workflow. Do not replace another chosen psalm
translation with the BCP Psalter without establishing the church's practice.
Read only the selected entries, not the entire data file into model context.

Keep source-designated alternatives and optional phrases distinct. Resolve
any bracketed choices for the actual day before printing; never include an
unfilled name slot or a list of mutually exclusive options in a bulletin.
A and B use a proper preface; C and D contain their own thanksgiving text.
Standard Form VI already includes a confession. The renderer follows it with
the absolution instead of repeating the separate confession. An explicit
confession omission removes that ending from the standard form. Private
versions and service variants retain their own confirmed order.
Seasonal acclamations and fraction forms must match the verified service.
Use the existing weekly `liturgy.files` map to select
`opening-acclamation-easter`, `opening-acclamation-lent`, or
`breaking-of-bread-lent` under the corresponding ordinary unit key. Ordinary
files remain the default. This lookup does not infer the season.

The prepared files select one source-supported option and omit optional local
names. Congregation-only prayer files retain responses and cues, with editorial
omissions recorded in comments. For weekly named petitions or other local
wording, prepare a verified private version from the source and the church's
confirmed input. Do not silently add or guess names.

Eleven verses in this source Psalter have no printed asterisk division. The
lookup preserves those as one undivided verse, with no invented response split.
The congregation continues at the next marked response.

## Lutheran licensed worship text

Modern ELW and Lutheran Service Book texts are not included in the public
plugin. Congregational-use licensing does not grant Labs permission to
redistribute those books. The publisher terms are linked in the third-party
notices. Do not copy licensed text into this repository or substitute an
older public-domain service while calling it ELW or LSB.

Save the church's setting and use its existing licensed local material first.
If material is missing, ask for one relevant recent bulletin or a permitted
export from its worship-planning resource. Explain that this establishes its
reusable worship text for later weeks. The agent does the extraction, source
comparison, formatting, and private-file preparation; the pastor should not
have to create six technical files or supply public-source URLs. Preserve
copyright notices and any conditions on local storage and use.

An ordinary return visit reuses the verified private units and asks only for
weekly changes. A license question must not prevent saving the church's
identity and worship choices, or starting another ready workflow.
