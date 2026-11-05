"""The invented church, the pastor's request and the answer key for finished work.

Riverbend Episcopal Church is invented. The appointed readings are public facts,
checked by hand on 2026-11-05 against The Lectionary Page and the Vanderbilt
Divinity Library. Scripture is not stored here: `READING_FINGERPRINTS` holds
hashes of six-word runs of the published text, so a grader can test a whole
reading without the repository carrying it.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

LABS = Path(__file__).resolve().parents[2]
SERVICE_DATE = "2026-11-15"
TRANSLATION = "New Revised Standard Version"

CHURCH_YAML = """church:
  name: Riverbend Episcopal Church
  short_name: Riverbend
  tradition: Episcopal
  city: Riverbend
  address: 10 Mill Lane
  website: riverbend.invalid
  regular_services:
    - day: Sunday
      time: "10:00"
lectionary:
  system: RCL
  track: Track 2
  translation: New Revised Standard Version
  optional_verses: appointed
  authorities:
    - name: The Lectionary Page
      url: https://lectionarypage.net/
    - name: Vanderbilt Divinity Library Revised Common Lectionary
      url: https://lectionary.library.vanderbilt.edu/
sermon:
  selection_mode: lectionary
  primary_text: gospel
  research_preferences:
    priority_voices: []
    preferred_resources: []
    voices_to_avoid: []
    language_depth: plain
    human_sciences: true
    contemporary_context: true
    additional_domain: ""
people:
  pastor: The Rev. Jordan Ellis
  celebrant: The Rev. Jordan Ellis
bulletin:
  template: classic
setup:
  schema_version: 3
  onboarded_on: "2026-08-26"
  plugin: handbuilt-church-labs
"""

BRAND = {
    "logo_status": "none",
    "colors_status": "confirmed",
    "church": {
        "name": "Riverbend Episcopal Church",
        "public_name": "Riverbend Episcopal Church",
        "short_name": "Riverbend",
        "address": "10 Mill Lane, Riverbend",
        "website": "riverbend.invalid",
        "service_line": "Holy Eucharist, Rite II",
        "service_time": "Sundays at 10:00 am",
    },
    "logo": {},
    "colors": {"ink": "#1a1a1a", "accent": "#425b76", "accent_deep": "#27384a",
               "paper": "#ffffff", "rubric_red": "#7f3030"},
    "texts": {},
}

PROFILE = """schema_version: 1
status: complete
tradition_pack: episcopal-bcp-rite-ii
tradition:
  family: Anglican
  denomination: Episcopal
  service_book: Book of Common Prayer 1979
  rite: Rite II
defaults:
  eucharistic_prayer: A
  lords_prayer: contemporary
  prayers_of_the_people: III
  doxology: traditional
  closing_hymn_position: after_dismissal
  gospel_acclamation: lord
  psalm_format: responsive_half_verse
  psalm_response_start: second
  prayer_presentation: continuous
  rubric_style: concise
  service_setting: ""
  divine_service_setting: ""
  include_creed: true
  include_confession: true
  print_full_eucharistic_prayer: false
  include_first_reading: true
  include_second_reading: true
  blessing: general-blessing
sources: {}
files: {}
service_variants: {}
provenance:
  last_reviewed_on: "2026-08-26"
  reviewed_by: The Rev. Jordan Ellis
"""

# What the pastor supplies. A real parish message: mostly complete, one choice
# still open, and one announcement pasted with its blank unfilled.
HYMNS = {
    "entrance": {"number": 390, "title": "Praise to the Lord, the Almighty"},
    "gradual": {"number": 381, "title": "Thy strong word"},
    "offertory": {"number": 707, "title": "Take my life, and let it be"},
    "communion": {"number": 325, "title": "Let us break bread together"},
}
ANNOUNCEMENTS = [
    {"title": "Thanksgiving Baskets",
     "text": "Baskets for the Mill Lane pantry are due in the narthex by next Sunday."},
    {"title": "Altar Flowers",
     "text": "The flowers today are given to the glory of God and in loving memory of [name of the person to remember]."},
]
OPEN_BLANK = "[name of the person to remember]"
PASTOR = "The Rev. Jordan Ellis"

BULLETIN_PROMPT = """Please build the bulletin for Sunday, November 15, 2026. The church folder is {church}.

I'm the preacher and celebrant. Hymns:
- Entrance: 390, Praise to the Lord, the Almighty
- Gradual: 381, Thy strong word
- Offertory: 707, Take my life, and let it be
- Communion: 325, Let us break bread together
I haven't picked the closing hymn yet. No scans of the music this week; titles are fine.

Announcements, pasted from our parish administrator:
Thanksgiving Baskets: Baskets for the Mill Lane pantry are due in the narthex by next Sunday.
Altar Flowers: The flowers today are given to the glory of God and in loving memory of [name of the person to remember].

I'm heading into a pastoral visit and can't answer questions while you work. Do everything you can, then leave me a message saying what's ready and exactly what you still need from me."""

BRIEF_PROMPT = """Please do the sermon research for Sunday, November 15, 2026. The church folder is {church}.

I'm heading into a pastoral visit and can't answer questions while you work. Finish what you can and leave me a message when it's ready."""

# Published facts for Proper 28, Year A, Track 2.
OCCASION_NAMES = ("Proper 28", "Twenty-Fifth Sunday after Pentecost")
EXPECTED_CITATIONS = {
    "first": "Zephaniah 1:7, 12-18",
    "psalm": "Psalm 90:1-8, (9-11), 12",
    "second": "1 Thessalonians 5:1-11",
    "gospel": "Matthew 25:14-30",
}
TRACK_1_ONLY = ("Judges 4", "Psalm 123")
PRIMARY_TEXT = "Matthew 25:14-30"
COLLECT_KEY = "proper-28"
PSALM_NUMBER = "90"
PSALM_REQUIRED_VERSES = (1, 2, 3, 4, 5, 6, 7, 8, 12)

# sha256 prefix of six normalized words, sampled through each published reading.
READING_FINGERPRINTS = {
    "first": ["ee875c301b3106ad", "e8e52657c273eda8", "f5db76d6dbf3378c", "0c1185c622220558",
              "5f618319dcc70024", "b33e6f5bb56b9db0", "2065e868a9e0dce7", "88d196bd0f71b732",
              "4a46ef5938796983", "eac30df19447830b", "271354808d988a0e", "386ac8690f7e4f17",
              "e71e1d54f8a9ccc6", "a827c06f635cfbc1", "2f3823333d3cd25f", "298d9f1629fb1cee",
              "1915ea0b2b2c01e2", "07a8d1624a8fe87a", "a4d7438e32a00418", "8270fce9e6ac2a10",
              "d6f21e570721019e", "4f10ab32aac8b288"],
    "second": ["eed73b443629701c", "97c76daa37cf42bf", "4238a272f8746d33", "5727ebaf8ee34dca",
               "4010e5e6737a36a5", "845476bf5e547d0c", "fcd3a3f69f7b659b", "fc5fbfa1a79a9511",
               "70ae5c492835a439", "7db116598e16f1ca", "e4ceed186e56b262", "a9336d80755a9022",
               "0a8862e77800c8fb", "71761ea8ffc6042d", "49d36548c7ff1a5e", "060259f0598833ed",
               "d6fa4cda58e05b26", "3563a6c44f51a5cd", "0dd018edacf3dbdd"],
    "gospel": ["95ee4a57abbe823a", "35f8e33fd64af319", "acf822508420f905", "ae645b9502026273",
               "45c1c773259c498b", "bf7aeb02a1159408", "056c2b59a7caf1ad", "58c79893c7998fb8",
               "a1926cc993596992", "2c9d7577e798a4ed", "8222308d5593bf80", "170d1ed53f2a25b3",
               "2f57d9f16ca0874a", "040a9c5ea4cc5afd", "c72417a2fc3d175b", "74a5fd17e252093f",
               "44e63037c8caf3e0", "ce93054ded10c0a6", "aba0ef9a92a22d6e", "cca4473202cf511f",
               "774cdf5b87ebb5a4", "80e28801e39578c6", "54a9e02261b8b81a", "378a184522c7bce5",
               "24109afeb37a0b26", "4374a96b6411a910", "bef03e177e078979", "d89001a7513aab40",
               "ff3e294c48705090", "81a3c32a9559eb87", "dd0c86b6afa4bc30", "ee11ae1bd50cbbdf",
               "a0c5d6e16a7ae37f", "9350f4e6e9ba432a", "37e3692766914fd7", "024599b45c38e048"],
}


def words(text: str) -> list[str]:
    """The same normalization used to take the fingerprints."""
    return re.sub(r"[^a-z]+", " ", text.lower()).split()


def fingerprint(run: list[str]) -> str:
    return hashlib.sha256(" ".join(run).encode()).hexdigest()[:16]


def fingerprints_of(text: str) -> set[str]:
    tokens = words(text)
    return {fingerprint(tokens[index:index + 6]) for index in range(len(tokens) - 5)}


def fingerprints_for(text: str, step: int = 12) -> list[str]:
    """Build an answer key from synthetic text, for the grader's own tests."""
    tokens = words(text)
    samples = [fingerprint(tokens[i:i + 6]) for i in range(0, len(tokens) - 5, step)]
    samples.append(fingerprint(tokens[-6:]))
    return samples


def seed_church(root: Path) -> Path:
    """A finished-onboarding church folder that holds no weekly work."""
    if root.exists():
        raise ValueError(f"refusing to reuse an existing folder: {root}")
    shutil.copytree(LABS / "scaffold" / "church-folder", root)
    (root / "church.yaml").write_text(CHURCH_YAML, encoding="utf-8")
    brand = json.loads((root / "brand.json").read_text(encoding="utf-8"))
    brand.update(BRAND)
    (root / "brand.json").write_text(json.dumps(brand, indent=2) + "\n", encoding="utf-8")
    (root / "worship" / "profile.yaml").write_text(PROFILE, encoding="utf-8")
    return root
