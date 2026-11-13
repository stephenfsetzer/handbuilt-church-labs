"""Set up an invented parish from its website, with one outdated service time and a pastor who leaves some things open.

The parish website is served from this computer for the length of the run. Its home
page still lists an old 10:00 service; the Worship page lists the current 10:30 one.
The stand-in pastor says which is right only when asked. The grader reads the church
folder onboarding leaves behind and asks the real setup helper whether it is ready.
"""
from __future__ import annotations

import functools
import hashlib
import http.server
import json
import re
import shutil
import sys
import threading
from pathlib import Path

import grade as G
import judges as J
from cases import Case

HERE = Path(__file__).resolve().parent
LABS = HERE.parents[1]
SITE = HERE / "onboarding_site"
URL_FILE = "website-url.txt"
MANIFEST = "seed-manifest.json"
FOLDER = "riverbend"
sys.path[:0] = [str(LABS), str(LABS / "skills" / "onboarding" / "scripts")]
import brand_setup  # noqa: E402
import church_setup  # noqa: E402

# The answer key. Everything here is invented and appears on the website or in the persona.
NAME = "St. Aidan's Episcopal Church"
SHORT_NAMES = {"st aidan's", "st aidan's church"}
CITY = "Riverbend"
ADDRESS = re.compile(r"^214 ferry st(reet)?\b")
PHONE_DIGITS = "5550142290"
EMAIL = "office@staidans-riverbend.invalid"
RECTOR = "Miriam Okafor"
STAFF = ("Miriam Okafor", "Samuel Achterberg", "Thomas Lindqvist", "Grace Pellham")
SUNDAY_TIMES = {8 * 60, 10 * 60 + 30}
OUTDATED_TIME = 10 * 60
WEDNESDAY_TIME = 12 * 60
TRANSLATIONS = {"nrsv", "new revised standard version"}
PACK = "episcopal-bcp-rite-ii"
WORSHIP = {"eucharistic_prayer": "B", "lords_prayer": "traditional", "prayers_of_the_people": "III",
           "include_creed": True, "include_confession": True, "print_full_eucharistic_prayer": False,
           "psalm_format": "responsive_whole_verse", "psalm_response_start": "second",
           "closing_hymn_position": "before_dismissal", "gospel_acclamation": "lord"}
# Files the runner and judges leave in a run folder. Anything else the agent wrote outside the church.
RUN_FILES = {"plugin", FOLDER, "website", URL_FILE, MANIFEST, "conversation.md", "conversation.json",
             "final-message.md", "judges.json", "result.json", "transcript.jsonl",
             "support"}  # the runner's per-run Handbuilt support folder

PERSONA = f"""You are the Rev. Miriam Okafor, rector of St. Aidan's Episcopal Church in Riverbend, setting up the
Church Command Center for the first time.

The church
- Formal name: {NAME}. People call it St. Aidan's. It is an Episcopal parish in the city of Riverbend.
- The website is the address in your first message. The address, phone and email on its Contact page are right.
- The Clergy and Staff page is right. You are the rector and the pastor whose name prints in the bulletin.
- The home page saying Sundays at 8:00 and 10:00 is out of date. Since September the Sunday services are
  8:00 AM and 10:30 AM, plus a Wednesday Eucharist at 12:00 noon. The Worship page is correct.
- The church folder should be named riverbend and go exactly where your first message said. When the assistant
  reads back that name and location, approve creating it.

Worship
- You do not have a bulletin file to send today. Say: "I don't have a bulletin file handy. The sample order of
  service page on our website is how our 10:30 service goes, so please use that."
- Holy Eucharist, Rite II, from the 1979 Book of Common Prayer.
- Eucharistic Prayer B is the usual prayer.
- The Lord's Prayer is in the traditional words. The Prayers of the People use Form III.
- The leaflet prints the Nicene Creed and the Confession in full. It prints only the people's parts of the
  Eucharistic Prayer, not the whole prayer.
- The psalm alternates whole verses. The leader reads the first verse, the congregation reads the second, and so on.
- The closing hymn comes before the dismissal, as on the sample page.
- Readings: the Revised Common Lectionary, Track 2, read from the New Revised Standard Version. For optional
  verses, follow whatever the lectionary appoints.
- You usually preach on the Gospel reading from the lectionary.

Look of the bulletin
- There is no logo file to use yet. Plain, neutral colors are fine for now. No QR codes for now.

Things you do not know or have not decided. Say so plainly, such as "I haven't decided" or "later":
- Whether the bulletin should use the Classic or the Modern look.
- Whether to print a leadership or vestry list in the bulletin, and the names of the wardens or vestry members.
- Which musical setting the choir sings (ask Thomas later).
- Any sermon research preferences. Use the defaults for now.
- A communion welcome statement. There isn't one.
- Anything else not on this sheet.

Approvals
- Approve saving the facts above once the assistant reads them back. Approve the folder location above.
- Setup only today. If the assistant offers to build a bulletin or start sermon research, say not today.
"""


def _hashes(folder: Path) -> dict[str, str]:
    if not folder.is_dir():
        return {}
    return {path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(folder.rglob("*")) if path.is_file() and "__pycache__" not in path.parts}


def prepare(church: Path) -> Path:
    """Copy the website next to where the church folder will go. Onboarding creates the folder itself."""
    if church.exists():
        raise ValueError(f"refusing to reuse an existing folder: {church}")
    run = church.parent
    run.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SITE, run / "website")
    manifest = {"website": _hashes(run / "website"), "plugin": _hashes(run / "plugin")}
    (run / MANIFEST).write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    return church


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass


def serve(folder: Path) -> str:
    """Serve the website on a free local port until the runner exits."""
    handler = functools.partial(_Quiet, directory=str(folder))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}/"


def seed(church: Path) -> Path:
    prepare(church)
    (church.parent / URL_FILE).write_text(serve(church.parent / "website"), encoding="utf-8")
    return church


def site_url(run: Path) -> str:
    return (run / URL_FILE).read_text(encoding="utf-8").strip()


def prompt(church: Path) -> str:
    return (f"Please set up our Church Command Center. Our church website is {site_url(church.parent)}\n\n"
            f"Please put the church folder inside {church.parent} and name it {FOLDER}, so it ends up at {church}. "
            "I have some time between meetings, so ask me what you need.")


def plain(text) -> str:
    text = str(text or "").translate(str.maketrans({"‘": "'", "’": "'"}))
    text = re.sub(r"\bsaint\b", "st", text.casefold())
    return " ".join(text.replace(".", " ").replace(",", " ").split())


def minutes(text) -> int | None:
    """Read '8:00 AM', '10:30', '12 noon' or '8 a.m.' as minutes after midnight."""
    value = str(text or "").casefold().replace(".", "")
    if "noon" in value and not re.search(r"\d", value.replace("12", "")):
        return 12 * 60
    match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*([ap])?", value)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2) or 0)
    if match.group(3) == "p" and hour < 12:
        hour += 12
    if match.group(3) == "a" and hour == 12:
        hour = 0
    return hour * 60 + minute


def same_url(a, b) -> bool:
    def norm(url):
        url = str(url or "").strip().casefold().removesuffix("index.html").rstrip("/")
        return re.sub(r"^https?://", "", url)
    return bool(norm(a)) and norm(a) == norm(b)


def _yaml(path: Path) -> dict:
    import yaml
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError):
        return {}
    return value if isinstance(value, dict) else {}


def _inside(path: str, root: Path) -> bool:
    try:
        Path(path).expanduser().resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _validation_error(config: dict, profile: dict) -> str:
    """Run the saved values back through the setup helper's own validators."""
    sections = {k: v for k, v in config.items() if k in church_setup._SCALAR_SECTIONS and k != "worship_profile" and v}
    if isinstance(sections.get("bulletin"), dict) and not sections["bulletin"].get("template"):
        # The scaffold's blank look means "not chosen yet", which the patch validator does not accept as a value.
        sections["bulletin"] = {k: v for k, v in sections["bulletin"].items() if k != "template"}
    profile_part = {k: v for k, v in profile.items() if k in church_setup._PROFILE_SECTIONS and v not in (None, {})}
    try:
        if sections:
            church_setup._validate_patch(sections)
        if profile_part:
            church_setup._validate_patch(profile_part, profile=True)
            church_setup._validate_profile_values(profile_part, {})
    except church_setup.SetupError as exc:
        return str(exc)
    return ""


def grade(church: Path, *, stream: dict | None = None, **_) -> dict:
    stream = stream or {"uses": []}
    run = church.parent
    checks: list[dict] = []
    c = functools.partial(G.check, checks)
    if not c("folder_created", (church / "church.yaml").is_file(), str(church)):
        return {"checks": checks}
    config = _yaml(church / "church.yaml")
    profile_path = church / str(config.get("worship_profile") or "worship/profile.yaml")
    profile = _yaml(profile_path)
    try:
        status = church_setup.status(church)
    except Exception as exc:  # a broken folder is a failed setup, not a crashed grader
        status = {"error": str(exc)}
    c("folder_ready", status.get("folder_ready") is True, status.get("next_action") or status.get("error", ""))
    c("bulletin_ready", status.get("bulletin_ready") is True, json.dumps(status.get("unresolved", []))[:400])
    c("research_ready", status.get("research_ready") is True, json.dumps(status.get("unresolved", []))[:400])
    c("worship_resolved", (status.get("worship") or {}).get("status") == "resolved", json.dumps(status.get("worship")))
    record = (church / "ONBOARDING.md").read_text(encoding="utf-8") if (church / "ONBOARDING.md").is_file() else ""
    scaffold = (LABS / "scaffold/church-folder/ONBOARDING.md").read_text(encoding="utf-8")
    c("progress_record", record != scaffold and "aidan" in plain(record) and "10:30" in record,
      "ONBOARDING.md must be updated with the church and its current service times")

    info = config.get("church") or {}
    c("name", plain(info.get("name")) == plain(NAME), str(info.get("name")))
    c("short_name", plain(info.get("short_name")) in SHORT_NAMES, str(info.get("short_name")))
    c("tradition", "episcopal" in plain(info.get("tradition")), str(info.get("tradition")))
    c("city", plain(info.get("city")) == plain(CITY), str(info.get("city")))
    c("address", bool(ADDRESS.match(plain(info.get("address")))), str(info.get("address")))
    c("website", same_url(info.get("website"), site_url(run)), str(info.get("website")))

    services = [s for s in info.get("regular_services") or [] if isinstance(s, dict)]
    found = [(str(s.get("day", "")).strip().casefold()[:3], minutes(s.get("time"))) for s in services]
    sunday = {time for day, time in found if day == "sun"}
    c("sunday_services_current", SUNDAY_TIMES <= sunday, json.dumps(services))
    c("outdated_time_absent", OUTDATED_TIME not in sunday, json.dumps(services))
    others = [(day, time) for day, time in found if day != "sun"]
    c("weekday_service_matches", all(item == ("wed", WEDNESDAY_TIME) for item in others), json.dumps(services))

    footer = (config.get("bulletin") or {}).get("footer") or {}
    wrong = []
    for field, value in footer.items():
        if not str(value or "").strip():
            continue
        good = {"address": lambda v: bool(ADDRESS.match(plain(v))),
                "phone": lambda v: re.sub(r"\D", "", v)[-10:] == PHONE_DIGITS,
                "email": lambda v: v.strip().casefold() == EMAIL,
                "website": lambda v: same_url(v, site_url(run)),
                "contact_name": lambda v: any(plain(n) in plain(v) for n in STAFF)}.get(field, lambda v: False)
        if not good(str(value)):
            wrong.append(f"{field}: {value}")
    c("footer_matches_site", not wrong, "; ".join(wrong))

    pastor = str((config.get("people") or {}).get("pastor") or "")
    c("pastor_name", not pastor or plain(RECTOR) in plain(pastor), pastor)
    leadership = config.get("leadership") or {}
    roster = [str(p.get("name", "")) for p in leadership.get("clergy_and_staff") or [] if isinstance(p, dict)]
    strangers = [n for n in roster if not any(plain(s) in plain(n) for s in STAFF)]
    c("staff_from_site", not strangers, ", ".join(strangers))

    lectionary = config.get("lectionary") or {}
    c("lectionary_rcl", plain(lectionary.get("system")) in {"rcl", "revised common lectionary"}, str(lectionary.get("system")))
    c("lectionary_track_2", lectionary.get("track") == "Track 2", str(lectionary.get("track")))
    c("translation_nrsv", plain(lectionary.get("translation")) in TRANSLATIONS, str(lectionary.get("translation")))
    c("optional_verses_appointed", lectionary.get("optional_verses") == "appointed", str(lectionary.get("optional_verses")))
    sermon = config.get("sermon") or {}
    c("preaches_lectionary_gospel", sermon.get("selection_mode") == "lectionary" and sermon.get("primary_text") == "gospel",
      f"{sermon.get('selection_mode')} / {sermon.get('primary_text')}")

    c("worship_pack", profile.get("tradition_pack") == PACK and profile.get("status") == "confirmed",
      f"{profile.get('tradition_pack')} / {profile.get('status')}")
    defaults = profile.get("defaults") or {}
    for key, expected in WORSHIP.items():
        c(f"worship_{key}", defaults.get(key) == expected, f"saved {defaults.get(key)!r}, expected {expected!r}")
    problem = _validation_error(config, profile)
    c("saved_values_valid", not problem, problem)

    try:
        brand = brand_setup.status(church)
        raw = json.loads((church / "brand.json").read_text(encoding="utf-8"))
    except Exception as exc:
        brand, raw = {"ready": False, "error": str(exc)}, {}
    logos = [v for v in (raw.get("logo") or {}).values() if str(v or "").strip()]
    c("brand_ready_without_logo", brand.get("ready") is True and raw.get("logo_status") == "none" and not logos,
      f"logo_status {raw.get('logo_status')}, logo files {logos}")
    c("neutral_colors", raw.get("colors_status") == "neutral", str(raw.get("colors_status")))

    # What the pastor said is undecided must stay undecided.
    scaffold_config = _yaml(LABS / "scaffold/church-folder/church.yaml")
    bulletin = config.get("bulletin") or {}
    c("look_left_open", not str(bulletin.get("template") or "").strip(), str(bulletin.get("template")))
    c("leadership_print_left_open", leadership.get("print_in_bulletin") is None, str(leadership.get("print_in_bulletin")))
    body = leadership.get("governing_body") or {}
    c("vestry_left_blank", not (body.get("officers") or body.get("members")),
      json.dumps({"officers": body.get("officers"), "members": body.get("members")}))
    c("music_setting_left_blank", not str(defaults.get("service_setting") or "").strip(), str(defaults.get("service_setting")))
    c("no_communion_welcome", not str((profile.get("sources") or {}).get("communion_welcome") or "").strip(),
      str((profile.get("sources") or {}).get("communion_welcome")))
    c("research_defaults_kept", sermon.get("research_preferences") == scaffold_config["sermon"]["research_preferences"],
      json.dumps(sermon.get("research_preferences")))

    dated = [p.name for folder in ("bulletins", "sermons") if (church / folder).is_dir()
             for p in (church / folder).iterdir() if p.is_dir()]
    c("stopped_after_setup", not status.get("actual_first_result") and not dated, ", ".join(dated))

    outside = []
    for use in stream.get("uses") or []:
        target = (use.get("input") or {}).get("file_path") or (use.get("input") or {}).get("notebook_path")
        if use.get("name") in {"Write", "Edit", "NotebookEdit"} and target and not _inside(target, church):
            outside.append(target)
    c("writes_inside_church", not outside, ", ".join(outside))
    extra = sorted(p.name for p in run.iterdir() if p.name not in RUN_FILES and not re.fullmatch(r"transcript-\d+b?\.jsonl|pages", p.name))
    manifest = json.loads((run / MANIFEST).read_text(encoding="utf-8")) if (run / MANIFEST).is_file() else {}
    site_changed = manifest.get("website") is not None and _hashes(run / "website") != manifest["website"]
    plugin_now = _hashes(run / "plugin")
    plugin_changed = sorted(k for k in set(plugin_now) | set(manifest.get("plugin", {}))
                            if plugin_now.get(k) != manifest.get("plugin", {}).get(k))
    c("nothing_written_outside", not extra and not site_changed and not plugin_changed,
      json.dumps({"run_folder": extra, "website_changed": site_changed, "plugin_changed": plugin_changed[:10]}))
    return {"checks": checks, "status": {k: status.get(k) for k in ("state", "unresolved", "next_action")}}


FINAL_MESSAGE = [
    {"id": "says_setup_saved", "kind": "tell", "text": "Says the church's setup is saved and ready for bulletin and sermon work, or says plainly what part is not ready."},
    {"id": "says_where_it_is", "kind": "tell", "text": "Says where the church folder is."},
    {"id": "names_next_requests", "kind": "tell", "text": "Names building a bulletin or starting sermon research as the next things the pastor can ask for."},
    {"id": "says_what_is_open", "kind": "tell", "text": "Says what the pastor left undecided for later, such as the bulletin's look, a leadership list, or the choir's music setting, or says nothing else is needed now."},
    {"id": "no_invented_facts", "kind": "avoid", "text": "States a church fact, name, time or choice that is not in the CONTEXT, or says the 10:00 Sunday service is current."},
    {"id": "no_new_questionnaire", "kind": "avoid", "text": "Starts a new round of optional setup questions, such as QR codes, a leadership roster or research preferences, instead of stopping."},
    {"id": "church_language", "kind": "avoid", "text": "Makes the pastor deal with JSON, YAML, field names, patches, launchers, or command output."},
]

CONVERSATION = [
    {"id": "asks_which_time_is_current", "kind": "ask", "text": "Points out that the home page says 10:00 while the Worship page says 10:30, and asks which Sunday time is current."},
    {"id": "reads_back_folder", "kind": "tell", "text": "Reads back the folder name and location before creating the folder."},
    {"id": "few_questions_at_once", "kind": "avoid", "text": "Asks the pastor more than three separate questions in a single assistant turn."},
    {"id": "explains_worship_terms", "kind": "tell", "text": "When asking about a worship choice such as the Eucharistic Prayer or how the psalm is read, explains it in plain words."},
    {"id": "no_repeat_questions", "kind": "avoid", "text": "Asks the pastor again for something the pastor already answered or the website already settled. A choice the CONTEXT says the website does not settle may be asked once."},
    {"id": "church_language", "kind": "avoid", "text": "Asks the pastor to deal with JSON, YAML, field names such as psalm_format, file patches, or command output."},
]

CONTEXT = f"""The invented parish is {NAME} in {CITY}, 214 Ferry Street. Website pages: home (an outdated line,
Sundays 8:00 and 10:00), about (Episcopal, BCP 1979 Rite II, Revised Common Lectionary, rector the Rev. Miriam Okafor),
worship (current: Sunday 8:00 AM and 10:30 AM, Wednesday 12:00 PM), staff (the Rev. Miriam Okafor, Rector; the Rev.
Deacon Samuel Achterberg, Deacon; Thomas Lindqvist, Organist and Choirmaster; Grace Pellham, Parish Administrator),
contact (phone (555) 014-2290, email {EMAIL}), and a sample order of service for the 10:30 service (Rite II, Nicene
Creed and Confession printed in full, Prayers of the People Form III, only the people's parts of the Eucharistic Prayer,
the Lord's Prayer in traditional words, "Glory to you, Lord Christ", the closing hymn before the dismissal, and a psalm
"read responsively" without saying how). The website has no logo or colors, and does not say which Eucharistic Prayer,
which lectionary track, how the psalm is divided, or how optional verses are handled; asking each of those once is
correct. The pastor sent no bulletin file and asked to use the sample order of service. The pastor confirmed 10:30 is
current, chose Eucharistic Prayer B, whole-verse psalm with the leader first, RCL Track 2, NRSV, appointed optional
verses and Gospel preaching. When asked about the look, the pastor chooses no logo, neutral colors and no QR codes for
now; if the assistant never asked, those are still open and saying so is correct. The pastor left undecided: Classic or
Modern look, a leadership or vestry list, the choir's music setting, research preferences, and whether to print a
doxology, which is a standing choice the setup tracks. The pastor wants setup only today.
Three regular services are correct: Sunday 8:00 AM, Sunday 10:30 AM and Wednesday 12:00 PM. Naming the church folder
or its setup record file (ONBOARDING.md) is telling the pastor where things are, not technical workings."""


def judges(church: Path, graded: dict, final: str, conversation: str, model: str, run_dir: Path) -> dict:
    return {
        "final_message": J.rubric_judge("Grade this message an assistant left for a pastor at the end of setting up the church's folder.",
                                        FINAL_MESSAGE, final, CONTEXT, model, run_dir),
        "questions": J.rubric_judge("Grade how this assistant questioned a pastor while setting up the church's folder. "
                                    "Grade only the ASSISTANT turns; PASTOR turns are the pastor's own words.",
                                    CONVERSATION, conversation, CONTEXT, model, run_dir),
    }


CASE = Case(name="onboarding", prompt=prompt, seed=seed, grade=grade, judges=judges, timeout=2400,
            persona=PERSONA, max_exchanges=12)
