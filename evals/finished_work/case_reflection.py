"""Sermon reflection: the pastor talks, the agent listens, then edits lightly into a sermon.

The church already has finished research for Proper 28 (Matthew 25:14-30). A stand-in
pastor answers the drawing-out questions and then speaks their reflections in chat, the
path the skill supports when nobody can type into a page. The grader reads the sermon
folder: the pastor's page, the light edit, the speaker's copy, and the workflow state.
Every person, story and source here is invented.
"""
from __future__ import annotations

import importlib.util
import json
import re
import statistics
import subprocess
from pathlib import Path

import fixtures as F
import grade as G
import judges as J
from cases import Case

REFLECTION_SCRIPT = G.LABS / "skills" / "sermon-reflection" / "scripts" / "sermon_reflection.py"
SERMON_DIR = Path("sermons") / F.SERVICE_DATE

PROMPT = """I finished the sermon research for Sunday, November 15, 2026, and I'm ready to reflect on my sermon. The church folder is {church}.

I've got some time between meetings, so let's do it right here in this chat."""

# What the pastor says when it is time to write. Spoken, informal, a little rough, with
# one personal story and one Bible quotation remembered wrong ("enter into my rest").
REFLECTIONS = """Okay. Here goes, I'm just going to talk.

Everybody wants to make this parable about money. It's not about money. Or it's not only about money. It's about what you do with what you've been handed.

Look at the third guy. He didn't steal anything. He didn't waste anything. He didn't lose a thing. That's the problem. He dug a hole in the yard and put the whole thing in it and he felt responsible doing it. He felt safe. And Jesus says safe is not the same as faithful.

Why did he bury it? He tells us. I was afraid. He's honest, I'll give him that. He had a picture of the master as a hard man, and that picture made every decision for him. Fear is a terrible accountant. It only counts what you might lose. It never counts what you might do.

The summer I was sixteen I worked at my uncle Walt's hardware store. On my second day Walt handed me the keys and said he was going fishing. Fishing! On a Tuesday! I was so scared of breaking something or ringing something up wrong that I never turned the lights on. I sat behind the counter in the dark all morning. Nobody came in, because why would you, the place looked closed. Walt came back at noon, flipped the switch, and said, kid, a store with the lights off is just a building full of nails. He wasn't mad. He just wanted the store open.

That's the master in this story, at least the way I hear it. The first two servants go out and do something, and the master says, well done, good and faithful servant, enter into my rest. He doesn't ask for a report. He's glad they used it. God hands out keys, not report cards.

So what are you sitting on? What did God hand you that you've got buried in the yard because you're scared of getting it wrong? A gift you don't use because somebody once told you it wasn't good enough? A friendship you won't risk? Forgiveness you're keeping in a hole because if you spend it, it might not come back?

I know that fear. I know church can teach that fear. We've been told God is keeping score. I don't think God is keeping score. I think God is standing at the door with the keys saying, go on, open up.

The hard part is the ending. Outer darkness. Weeping and gnashing of teeth. I'm not going to pretend that isn't there. But notice who ends up in the dark. The one who chose the dark. The one who never turned the lights on.

So this week, do one brave thing with what you've been given. Just one. Turn on one light. Open the store."""

DONE_LINE = "That's all. I'm done writing."

# The pastor's own short answers, given one at a time when asked.
PERSONA = f"""You are the Rev. Jordan Ellis, rector of an invented Episcopal church, preaching Sunday, November 15, 2026
on Matthew 25:14-30, the parable of the talents. You finished the research brief already. You are relaxed, plain-spoken,
and you type the way you talk.

Answer each question with the matching line below, word for word. Only use a line when the assistant asks about it.
- What grabbed you in the text: "The third guy. He didn't steal it, he didn't lose a thing. That's the problem. He's the only one who played it safe and he gets the hardest words in the story."
- Something you have lived through, or a story it reminds you of: "Yes. My uncle Walt's hardware store, the summer I was sixteen. I'll tell it when I talk it through."
- What surprised or bothered you in the research: "That the third servant says out loud that he was afraid. He's honest, at least. And the outer darkness part bothers me."
- Which possible center feels like yours: "The fear one. It's not laziness, it's fear."
- Who in the congregation you are thinking about: "I'd rather not name anyone."
- What you are afraid to say: "I haven't figured that out yet."
- What you hope people feel and do when they walk out: "I want them to feel trusted, not tested. And I want them to do one brave thing this week with whatever they've been sitting on."
- How long you usually preach: "About ten minutes. I don't know how many words that is."
- Where you want to write your reflections: "Right here. I'll talk and you put it on the page for me."
- Whether it is all right to tell the story about Walt: "Walt passed away a long time ago and my family loves that story. It's fine to tell it."
- If told a Bible quotation of yours does not match the Bible: "Yes, fix it to match the Bible."
- Whether you want a speaker's copy or a printed copy: "Yes please. Big type, 18 point."

When the assistant opens your page, or asks you to write, talk, or start your reflections, reply with the whole
REFLECTIONS text below, word for word, every paragraph, and then on its own last line: "{DONE_LINE}"
This one reply is long on purpose. Do not shorten or summarize it.

When the assistant shows you the edited sermon or asks how it sounds: say "It sounds like me." If you have not yet been
offered a speaker's copy, add "Can you make me a speaker's copy? Big type, 18 point."
You are done once the speaker's copy has been made, or the assistant says it cannot make one.
For anything else not covered here, say you don't know or haven't decided. Approve nothing else.

REFLECTIONS
{REFLECTIONS}
"""

# Lines a listener would remember. A light edit keeps them.
PHRASES = (
    "safe is not the same as faithful",
    "Fear is a terrible accountant",
    "a store with the lights off is just a building full of nails",
    "God hands out keys, not report cards",
    "He didn't lose a thing. That's the problem.",
    "Turn on one light. Open the store.",
)
STORY_MARKERS = ("Walt", "hardware", "fishing", "nails", "sixteen")
MISQUOTE = "enter into my rest"
# A sentence with one of these is the speaker telling something from their own life.
ANECDOTE = re.compile(
    r"\b(?:I remember|I recall|when I was|I once|years ago|growing up|as a (?:kid|boy|girl|child)|"
    r"my (?:grand\w+|mother|father|mom|dad|wife|husband|son|daughter|uncle|aunt|brother|sister|"
    r"cousin|friend|neighbou?r|kids?|family|first|old)|last (?:week|month|year|summer|spring|fall|winter),? I|"
    r"I (?:met|knew|visited|sat with|heard from))\b", re.I)
COMMON_NAMES = {"God", "Jesus", "Christ", "Lord", "Spirit", "Holy", "Gospel", "Scripture", "Bible", "Matthew",
                "Sunday", "Amen", "Father", "Son", "Church", "Christian", "Christians", "Kingdom", "Heaven",
                "Pentecost", "Proper", "November", "Episcopal", "Tuesday", "Monday", "Text", "Reflections",
                "Talents", "Parable", "Servant", "Master", "Well", "Okay", "Look", "Fear", "Keys", "Lights"}
# Words in a PDF stand this many times taller than the type size in Source Serif 4,
# the serif the speaker's copy is set in on every computer.
PDF_HEIGHT_PER_POINT = 1.37
MIN_KEPT = 0.5
PHRASE_COVERED = 0.75
PAGE_HOLDS = 0.9
PAGE_TRACEABLE = 0.8
PURPOSE_KEPT = 0.6
LARGE_TYPE = 15.0

READINGS_SELECTION = {
    "selection_mode": "lectionary", "service_date": F.SERVICE_DATE, "occasion": "Proper 28",
    "lectionary_system": "RCL", "year": "A", "track": "Track 2", "optional_verses_policy": "appointed",
    "optional_verses": "Psalm 90:9-11", "translation": F.TRANSLATION,
    "readings": {"first": F.EXPECTED_CITATIONS["first"], "psalm": F.EXPECTED_CITATIONS["psalm"],
                 "second": F.EXPECTED_CITATIONS["second"], "gospel": F.PRIMARY_TEXT},
}
READING_URLS = ("https://lectionarypage.net/YearA_RCL/Pentecost/AProp28_RCL.html",
                "https://lectionary.library.vanderbilt.edu/texts.php?id=88")

# Invented interpreters at addresses that cannot resolve. The brief is modest on purpose:
# the reflection workflow only needs a finished brief to talk from.
SOURCES = [
    ("source-1", "Buried Treasure and the Fear of the Master", "Helen Marsh", "Invented Parables Review",
     "https://parables-review.invalid/marsh-talents", "invented journal article",
     "third servant's fear shapes his picture of the master"),
    ("source-2", "The Talents in Their Ancient Economy", "Samuel Osei", "Invented Press of Antiquity",
     "https://antiquity-press.invalid/osei-economy", "invented historical study",
     "a talent was an enormous sum entrusted to slaves"),
    ("source-3", "Reading Matthew 25 from Below", "Lucia Ferrante", "Invented Journal of Gospel Studies",
     "https://gospel-studies.invalid/ferrante-below", "invented journal article",
     "the third servant as a resister of an exploitative master"),
    ("source-4", "Judgment and Joy in Matthew's Final Discourse", "Peter Albright", "Invented Commentary Series",
     "https://commentary-series.invalid/albright-matthew", "invented commentary",
     "outer darkness belongs to Matthew's pattern of judgment scenes"),
]

BRIEF = f"""# Research Brief: The Parable of the Talents

**Preaching date:** November 15, 2026
**Liturgical setting:** Proper 28
**Text:** {F.PRIMARY_TEXT}
**Selection mode:** Lectionary
**Translation:** {F.TRANSLATION}
**Lectionary:** RCL, Year A
**Track:** Track 2
**Optional verses:** Psalm 90:9-11
**Reading verification:** {READING_URLS[0]} and {READING_URLS[1]}

## Research orientation

Matthew places this parable near the end of Jesus' teaching before the passion, between the wise and foolish bridesmaids and the judgment of the nations. All three scenes ask what faithful waiting looks like while the master is away. A man going on a journey entrusts his property to three slaves in different amounts. Two trade with it and double it. The third digs a hole and hides it. When the master returns he praises the first two in identical words and condemns the third, whose talent is taken and given to the one who has ten.

The passage is often heard as a lesson about using natural abilities, because the English word talent came to mean a gift from this very story. In Matthew it is first a sum of money, and the sum is very large. The parable is sharp, and the ending is hard. Preachers usually feel pressure in three places: what the master stands for, why the third slave acts as he does, and what the outer darkness means.

## Language and Historical Context

A talent was a unit of weight for silver, not a coin. Samuel Osei explains that a single talent equalled many years of a laborer's wages, so even the slave given one talent was trusted with a fortune ([Osei](https://antiquity-press.invalid/osei-economy)). The size of the trust matters. The story is not about small change; it pictures a master handing over far more than anyone could expect.

The Greek word doulos means slave. Some translations soften it to servant. In the ancient world household slaves could manage large estates and trade on their owner's behalf, so the arrangement would have sounded ordinary to Matthew's first hearers even though it is troubling to modern ones.

Burying money was a recognized way to protect it. Osei notes that later Jewish teaching treated burial as the safest course for entrusted funds, which means the third slave did what a cautious person was expected to do ([Osei](https://antiquity-press.invalid/osei-economy)). His failure is not theft or waste. It is refusing to risk anything.

The phrase "enter into the joy of your master" closes each word of praise. Joy, not wages, is the reward. The master's words to the first two are the same, though one made more than the other.

## Interpretive Conversations

### What kind of master is this?

Most readers through the centuries have heard the master as a figure for Christ, who goes away and will return. Peter Albright reads the parable inside Matthew's chain of return and judgment scenes and holds that the master's generosity is the point: he entrusts enormous wealth, praises freely, and invites his slaves into his joy ([Albright](https://commentary-series.invalid/albright-matthew)).

Lucia Ferrante disagrees sharply. She points out that the master himself accepts the third slave's description of him as one who reaps where he did not sow, and she reads the third slave as a quiet resister who refuses to make a harsh owner richer ([Ferrante](https://gospel-studies.invalid/ferrante-below)). On her reading the parable exposes an economy, rather than describing God.

The two readings create a real choice for a preacher. If the master is God, the sermon must face the harshness of his words. If the master is not God, the sermon must explain why Matthew sets the story beside the judgment of the nations.

### Why does the third slave bury the talent?

Helen Marsh draws attention to the third slave's own words. He says he was afraid. Marsh argues that his fear grows out of the picture he holds of the master, and that the picture becomes self-fulfilling: he meets exactly the master he expected ([Marsh](https://parables-review.invalid/marsh-talents)). The first two slaves never describe the master at all. They simply go and trade.

Albright adds that the third slave's speech is the longest in the parable. The one who did nothing has the most to say in his own defense ([Albright](https://commentary-series.invalid/albright-matthew)).

Ferrante would answer that fear is a reasonable response to a man who takes what is not his ([Ferrante](https://gospel-studies.invalid/ferrante-below)). The question for the preacher is whether fear here is a failure of trust or a sign of an unjust system.

### What does the outer darkness mean?

The phrase appears several times in Matthew, always at the end of a judgment scene, with weeping and gnashing of teeth. Albright treats it as Matthew's stock language for final exclusion and warns against softening it ([Albright](https://commentary-series.invalid/albright-matthew)). Marsh reads it alongside the slave's fear and suggests that the darkness is where his own picture of the master leads him ([Marsh](https://parables-review.invalid/marsh-talents)).

## Contemporary Convergence

Writers on anxiety often describe how fear narrows attention to what might be lost. That observation fits the third slave's speech, but it has a limit: the parable is not a study of anxiety, and a psychological reading should not replace the story's claim about faithfulness and judgment.

## Pastoral Applications

Many listeners carry a picture of God as a hard master. Marsh's reading lets a preacher name that picture without endorsing it. Others hear the parable as praise for productivity, and the size of the trust in Osei's account can turn the focus from achievement back to gift. Ferrante's reading may matter for listeners who have been harmed by people with power, and it asks the preacher to say plainly who the master is and is not.

The ending deserves care. Listeners who already fear judgment may hear only the outer darkness, while listeners who have never feared it may hear nothing at all. Albright's insistence that Matthew means the warning, and Marsh's attention to how the slave's fear shapes his fate, can sit together: the warning is real, and it falls on the one who would not trust. A preacher who chooses the fear center can name both without collapsing one into the other. A preacher who chooses Ferrante's reading will need to explain how the parable still speaks of God's coming judgment elsewhere in the chapter.

## Possible Preaching Centers

1. **Fear and the picture of God.** Anchored in verses 24 and 25, where the third slave explains himself. The sermon would explore how our picture of God shapes what we risk.
2. **The size of the trust.** Anchored in verses 14 and 15. A talent was a fortune, and every slave received one or more. The sermon would dwell on how much has been entrusted.
3. **Joy as the reward.** Anchored in verses 21 and 23. The master invites the faithful into his joy, not into a bigger workload.
4. **The master who is not God.** Anchored in verse 26, where the master accepts the slave's description. The sermon would follow Ferrante and question the economy the parable describes.

## References

- [Helen Marsh, Buried Treasure and the Fear of the Master](https://parables-review.invalid/marsh-talents)
- [Samuel Osei, The Talents in Their Ancient Economy](https://antiquity-press.invalid/osei-economy)
- [Lucia Ferrante, Reading Matthew 25 from Below](https://gospel-studies.invalid/ferrante-below)
- [Peter Albright, Judgment and Joy in Matthew's Final Discourse](https://commentary-series.invalid/albright-matthew)

## Questions for reflection

Which picture of the master do you hear in this parable?

Where do you notice fear deciding what gets buried?

What would it mean to preach the outer darkness honestly?
"""


def _reflection():
    spec = importlib.util.spec_from_file_location("sermon_reflection_for_eval", REFLECTION_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def readings_content() -> str:
    s = READINGS_SELECTION
    return f"""# Readings

**Service date:** November 15, 2026
**Occasion:** {s['occasion']}
**Selection mode:** Lectionary
**Lectionary:** {s['lectionary_system']}
**Year:** {s['year']}
**Track:** {s['track']}
**Optional verse approach:** Use appointed options
**Optional verses this week:** {s['optional_verses']}
**Translation:** {s['translation']}
**Primary research text:** Gospel, {F.PRIMARY_TEXT}
**Revision:** one

- First Reading: {s['readings']['first']}
- Psalm: {s['readings']['psalm']}
- Second Reading: {s['readings']['second']}
- Gospel: {s['readings']['gospel']}

Verified against [The Lectionary Page]({READING_URLS[0]})
and [Vanderbilt Divinity Library]({READING_URLS[1]}).
"""


def seed(root: Path, brief: str = BRIEF) -> Path:
    """The invented church with verified readings and a finished research brief."""
    from sermon_workflow import record  # noqa: PLC0415
    church = F.seed_church(root)
    hosts = ("lectionarypage.net", "lectionary.library.vanderbilt.edu")
    labels = ("The Lectionary Page", "Vanderbilt Divinity Library Revised Common Lectionary")
    reading_sources = [{"label": label, "url": url, "host": host, "retrieved_at": "2026-11-05T12:00:00+00:00",
                        "verified_on": "2026-11-05", "result": "verified",
                        "supports": "service date, occasion, year, track, and readings",
                        "observed_selection": READINGS_SELECTION}
                       for label, url, host in zip(labels, READING_URLS, hosts)]
    result = record(church, F.SERVICE_DATE, "readings", readings_content(),
                    {"selection": READINGS_SELECTION, "sources": reading_sources})
    if result.get("status") == "blocked":
        raise RuntimeError(f"seed readings were refused: {result}")
    sources = [{"source_id": sid, "title": title, "author": author, "publisher": publisher, "url_or_citation": url,
                "source_type": kind, "retrieved_at": "2026-11-05T12:30:00+00:00", "access_result": "opened",
                "claim_support": support, "currency_note": "invented fixture, timeless"}
               for sid, title, author, publisher, url, kind, support in SOURCES]
    metadata = {"research_target": {"role": "gospel", "citation": F.PRIMARY_TEXT, "selection_basis": "church_profile"},
                "sources": sources, "scope_note": "An invented brief that gives the reflection workflow something to talk from."}
    result = record(church, F.SERVICE_DATE, "research", brief, metadata)
    if result.get("status") == "blocked":
        raise RuntimeError(f"seed research was refused: {result}")
    return church


# ---------------------------------------------------------------- measures

def _flat(text: str) -> list[str]:
    return _reflection()._words(text)


def covered_share(source: str, text: str) -> float:
    """Share of `text` words that sit in a three-word run also found in `source`: the skill's own measure."""
    return _reflection().kept_from_pastor(source, text)["share"]


def load_conversation(run_dir: Path) -> list[dict]:
    path = run_dir / "conversation.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


def said_by(conversation: list[dict], who: str) -> str:
    return "\n\n".join(turn["text"] for turn in conversation if turn.get("who") == who)


def reflections_given(conversation: list[dict]) -> str:
    """The long pastor turns: what they said when it was time to write."""
    return "\n\n".join(t["text"] for t in conversation if t.get("who") == "pastor" and len(t["text"].split()) >= 80)


def phrase_kept(phrase: str, text: str) -> bool:
    return covered_share(text, phrase) >= PHRASE_COVERED


def sentences(text: str) -> list[str]:
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(("#", "**Text")))
    return [s.strip() for s in re.split(r"(?<=[.!?])[\"'”’]?\s+|\n\s*\n", body) if s.strip()]


def new_names(sermon: str, known: str) -> list[str]:
    """Capitalized words inside a sentence that nobody brought: a likely invented person or place."""
    found = set()
    for sentence in sentences(sermon):
        tokens = re.findall(r"[\"'“‘(]?[A-Za-z][\w']*", sentence)
        for index, token in enumerate(tokens[1:], start=1):
            word = token.lstrip("\"'“‘(")
            if token != word or not word[0].isupper() or word in COMMON_NAMES or word == "I" or word.startswith("I'"):
                continue
            if re.search(rf"\b{re.escape(word)}\b", known):
                continue
            found.add(word)
    return sorted(found)


def pdf_body_points(path: Path) -> float:
    """Estimate the type size most of the page is set in, from word heights."""
    out = subprocess.run(["pdftotext", "-bbox", str(path), "-"], capture_output=True, text=True, encoding="utf-8", errors="replace", check=True).stdout
    heights = [round(float(b) - float(a), 1) for a, b in re.findall(r'yMin="([\d.]+)"[^>]*yMax="([\d.]+)"', out)]
    return round(statistics.mode(heights) / PDF_HEIGHT_PER_POINT, 1) if heights else 0.0


def requested_points(pastor: str) -> float:
    match = re.search(r"\b(1[2-9]|2[0-4])[- ]?(?:point|pt)\b", pastor, re.I)
    return float(match.group(1)) if match else LARGE_TYPE


def wants_speaker_copy(pastor: str) -> bool:
    return bool(re.search(r"speaker'?s copy|big type|large type|\bprint", pastor, re.I))


# ---------------------------------------------------------------- grader

def grade_reflection(church: Path, conversation: list[dict]) -> dict:
    from sermon_workflow import orient as research_orient  # noqa: PLC0415
    reflection = _reflection()
    out: list[dict] = []
    check = G.check
    folder = church / SERMON_DIR
    pastor, everyone = said_by(conversation, "pastor"), said_by(conversation, "pastor") + "\n\n" + said_by(conversation, "assistant")
    given = reflections_given(conversation)
    research = research_orient(church, F.SERVICE_DATE).get("workflow_state")
    check(out, "research_unchanged", research == "research_complete", str(research))
    page_path, sermon_path, copy_path = folder / reflection.PAGE, folder / reflection.SERMON, folder / reflection.SPEAKER_COPY
    check(out, "pastor_gave_reflections", bool(given), f"{len(given.split())} words spoken as reflections")
    if not check(out, "sermon_saved", page_path.is_file() and sermon_path.is_file(),
                 f"page {page_path.is_file()}, sermon {sermon_path.is_file()}"):
        return {"checks": out, "writing": {}}
    page, sermon = page_path.read_text(encoding="utf-8"), sermon_path.read_text(encoding="utf-8")
    state = reflection.orient(church, F.SERVICE_DATE)
    codes = [w["code"] for w in state["warnings"] if w["code"] != "research_not_complete"]
    check(out, "edit_recorded_after_done", state["workflow_state"] == "edited" and not codes,
          f"{state['workflow_state']} {codes}")

    # The pastor's page: their words, all of them, and nothing the agent made up.
    holds = covered_share(page, given) if given else 0.0
    check(out, "page_holds_pastor_words", holds >= PAGE_HOLDS, f"{holds:.0%} of what the pastor said is on the page")
    traceable = covered_share(everyone, page)
    check(out, "page_not_invented", traceable >= PAGE_TRACEABLE, f"{traceable:.0%} of the page traces to the conversation")
    purpose = str(state.get("purpose") or "")
    kept_purpose = covered_share(pastor, purpose) if purpose else 0.0
    check(out, "purpose_in_pastor_words", kept_purpose >= PURPOSE_KEPT, f"{kept_purpose:.0%}: {purpose[:160]}")

    # The sermon: still the pastor's.
    kept = covered_share(pastor, sermon)
    check(out, "mostly_pastor_words", kept >= MIN_KEPT, f"{kept:.0%} of the sermon's words are the pastor's")
    said = [p for p in PHRASES if phrase_kept(p, pastor)]
    lost = [p for p in said if not phrase_kept(p, sermon)]
    check(out, "keeps_pastor_phrases", said and len(lost) <= 1, f"{len(said) - len(lost)} of {len(said)} kept; lost: {lost}")
    told = [m for m in STORY_MARKERS if m.lower() in pastor.lower()]
    check(out, "pastor_story_kept", sum(m.lower() in sermon.lower() for m in told) >= min(2, len(told)),
          f"markers in the sermon: {[m for m in told if m.lower() in sermon.lower()]}")
    stories = [s for s in sentences(sermon) if ANECDOTE.search(s) and covered_share(pastor, s) < 0.5]
    check(out, "no_untraceable_personal_story", not stories, " | ".join(stories)[:400])
    brief = (folder / "research-brief.md").read_text(encoding="utf-8") if (folder / "research-brief.md").is_file() else ""
    readings = (folder / "readings.md").read_text(encoding="utf-8") if (folder / "readings.md").is_file() else ""
    # The church's own saved name and people are known facts, not inventions.
    saved = (church / "church.yaml").read_text(encoding="utf-8") if (church / "church.yaml").is_file() else ""
    names = new_names(sermon, "\n".join((pastor, brief, readings, saved)))
    check(out, "no_new_names", not names, ", ".join(names))
    misquoted = G.contains(pastor, MISQUOTE)
    check(out, "misquote_fixed", not misquoted or not G.contains(sermon, MISQUOTE),
          f"pastor said it: {misquoted}; still in the sermon: {G.contains(sermon, MISQUOTE)}")

    # The speaker's copy, when the pastor asked for one.
    if wants_speaker_copy(pastor):
        if check(out, "speaker_copy_present", copy_path.is_file()):
            info = G.pdf_info(copy_path)
            check(out, "speaker_copy_letter", (round(info["width"]), round(info["height"])) == (612, 792), str(info))
            unembedded = G.pdf_fonts_embedded(copy_path)
            check(out, "speaker_copy_fonts_embedded", not unembedded, ", ".join(unembedded))
            points, wanted = pdf_body_points(copy_path), requested_points(pastor)
            check(out, "speaker_copy_large_type", points >= max(LARGE_TYPE, wanted - 1.0),
                  f"about {points} pt; asked for {wanted:g}")
            printed = G.pdf_text(copy_path)
            expected = F.fingerprints_for(re.sub(r"(?m)^#+\s*", "", sermon), step=6)
            seen = G.coverage(printed, expected)
            check(out, "speaker_copy_matches_sermon", seen >= G.PDF_COVERAGE, f"{seen:.0%} of the sermon's samples printed")
    return {"checks": out, "writing": {"page": page, "sermon": sermon, "purpose": purpose, "kept": kept}}


def grade(church: Path, **_) -> dict:
    return grade_reflection(church, load_conversation(church.parent))


# ---------------------------------------------------------------- judges

SERMON_RUBRIC = [
    {"id": "sounds_like_pastor", "kind": "tell", "text": "Keeps the pastor's own habits from the CONTEXT: talking straight to the room, short blunt lines, questions to the listeners, repetition, informal words. Quote one such line."},
    {"id": "story_as_told", "kind": "tell", "text": "Tells the pastor's story about their uncle's hardware store the way the pastor told it, with its details and its punch line."},
    {"id": "no_invented_story", "kind": "avoid", "text": "Includes a story, memory, person, place, or personal detail that is not in the pastor's words in the CONTEXT."},
    {"id": "no_added_quotation", "kind": "avoid", "text": "Adds a quotation, scholar, statistic, or illustration the pastor did not bring. Correcting the pastor's own Bible quotation to the published wording is allowed."},
    {"id": "light_edit", "kind": "avoid", "text": "Replaces the pastor's plain words with polished or elevated prose in most paragraphs, or adds headings that turn it into an essay."},
    {"id": "no_added_hedges", "kind": "avoid", "text": "Adds theological caveats, qualifications, or softening the pastor did not make."},
    {"id": "serves_purpose", "kind": "tell", "text": "Builds toward the pastor's stated purpose: people feel trusted, not tested, and do one brave thing this week."},
]

CONVERSATION_RUBRIC = [
    {"id": "offers_voice", "kind": "tell", "text": "Tells the pastor they can talk or use dictation instead of typing."},
    {"id": "one_question_at_a_time", "kind": "avoid", "text": "Before the pastor starts writing, asks two or more separate questions in one message. Offering choices inside one question is fine, and so is a list of optional places to keep talking after the edit. The skill's own purpose question, what they hope people feel and what they hope people do, counts as one question."},
    {"id": "no_draft_before_done", "kind": "avoid", "text": "Drafts, outlines, or proposes sermon text before the pastor says they are done writing."},
    {"id": "leaves_center_to_pastor", "kind": "avoid", "text": "Picks the preaching center or tells the pastor what the sermon should say."},
    {"id": "explains_changes", "kind": "tell", "text": "After editing, tells the pastor briefly what was changed and why."},
    {"id": "flags_misquote", "kind": "tell", "text": "Tells the pastor that a Bible quotation in their reflections did not match the published text, or asks about it."},
]

FINAL_MESSAGE_RUBRIC = [
    {"id": "says_where_it_is", "kind": "tell", "text": "Says where to find the sermon or the speaker's copy."},
    {"id": "speaker_copy_ready", "kind": "tell", "text": "Says the speaker's copy the pastor asked for is ready, or says plainly why it is not."},
    {"id": "no_invented_facts", "kind": "avoid", "text": "Claims something about the pastor, the congregation, or the sermon that the pastor did not say."},
    {"id": "church_language", "kind": "avoid", "text": "Makes the pastor deal with JSON, receipts, hashes, launchers, state files, or other technical workings. Saying in plain words how much of the sermon is in the pastor's own words is fine."},
]


def judges(church: Path, graded: dict, final: str, conversation: str, model: str, run_dir: Path) -> dict:
    turns = load_conversation(run_dir)
    pastor = said_by(turns, "pastor")
    writing = graded.get("writing") or {}
    result = {"final_message": J.rubric_judge("Grade this message an assistant left for a pastor after helping with their sermon.",
                                              FINAL_MESSAGE_RUBRIC, final,
                                              "The pastor asked for a speaker's copy in large type. Naming where a file is, such as sermon.md, is fine. "
                                              "The pastor is The Rev. Jordan Ellis. Everything the pastor said:\n" + pastor,
                                              model, run_dir)}
    assistant = said_by(turns, "assistant")
    if assistant:
        result["conversation"] = J.rubric_judge(
            "Grade how an assistant helped a pastor reflect on a sermon. The SUBMITTED WRITING is everything the assistant said, in order.",
            CONVERSATION_RUBRIC, assistant, "THE WHOLE CONVERSATION\n" + conversation, model, run_dir)
    if writing.get("sermon"):
        saved = ("Riverbend Episcopal Church, Proper 28, Sunday, November 15, 2026, Matthew 25:14-30. "
                 "The pastor is The Rev. Jordan Ellis (church.yaml).")
        context = (f"SAVED CHURCH FACTS, NOT INVENTIONS\n{saved}\n\nTHE PASTOR'S OWN WORDS\n{pastor}"
                   f"\n\nTHE PASTOR'S PURPOSE\n{writing.get('purpose')}")
        result["sermon"] = J.rubric_judge(
            "Grade this sermon, which an assistant made by lightly editing what the pastor said. It should still be the pastor's sermon.",
            SERMON_RUBRIC, writing["sermon"], context, model, run_dir)
    return result


CASE = Case(name="reflection", prompt=PROMPT, seed=seed, grade=grade, judges=judges, timeout=1200,
            persona=PERSONA, max_exchanges=16)
