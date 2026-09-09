from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tests.helpers import bulletin_input

from skills.bulletin.renderer.render_bulletin import (
    can_merge_back_page,
    announcements_block,
    blessing_block,
    build_css,
    build_full_content,
    footer_line,
    hymn_block,
    inline_md,
    leadership_block,
    liturgy_steps,
    _qr_copy,
    qr_block,
    psalm_block,
    service_variant_order,
)
import skills.bulletin.renderer.render_bulletin as renderer


class BulletinRendererSemanticsTest(unittest.TestCase):
    def test_psalm_response_preserves_bold_markup(self) -> None:
        html = psalm_block({
            "number": "105:1",
            "text": "1 We give you thanks, O God, *\n\n"
                     "**we make known your deeds among the peoples,**",
        })
        self.assertIn(
            "<strong>we make known your deeds among the peoples,</strong>",
            html,
        )
        self.assertNotIn("**", html)

    def test_lyrics_render_as_structured_black_and_white_text(self) -> None:
        html = hymn_block(
            "Closing Hymn",
            {
                "title": "Dawn of Mercy",
                "tune": "SUNLIT PATH",
                "lyrics": [
                    {"part": "Choir", "lines": ["Morning opens wide"]},
                    {"part": "People", "people": True,
                     "lines": ["We walk in hope"]},
                    {"speaker": "All", "bold": True, "lines": ["Light guides us"]},
                ],
                "lyric_columns": 2,
            },
            Path("/tmp"),
        )
        self.assertIn('class="lyrics lyrics-2col"', html)
        self.assertIn('class="lyrics-speaker">Choir</span>', html)
        self.assertIn(
            '<div class="lyrics-group response">',
            html,
        )
        self.assertIn("We walk in hope", html)
        self.assertIn("Light guides us", html)
        self.assertIn("lyrics-2col", html)
        self.assertNotIn("hymn-img", html)

    def test_leadership_and_serving_shapes_are_normalized(self) -> None:
        brand = {
            "church": {"name": "Synthetic Church"},
            "leadership": {
                "print_in_bulletin": True,
                "clergy_and_staff": [{"role": "Pastor", "name": "Alex Reed"}],
                "governing_body": {
                    "label": "Council",
                    "officers": [{"role": "Chair", "name": "Morgan Lee"}],
                    "members": ["Alex Reed", "Taylor Kim"],
                },
            },
        }
        html = leadership_block(brand)
        self.assertIn("Alex Reed", html)
        self.assertIn("Council", html)
        self.assertEqual(html.count("Alex Reed"), 1)

    def test_governing_body_label_has_no_default(self) -> None:
        html = leadership_block({
            "church": {"name": "Synthetic Church"},
            "leadership": {"print_in_bulletin": True,
                            "governing_body": {"members": ["Taylor Kim"]}},
        })
        self.assertIn("Taylor Kim", html)
        self.assertNotIn("Vestry", html)
        self.assertNotIn("Council", html)

    def test_leadership_requires_explicit_print_consent(self) -> None:
        self.assertEqual(leadership_block({
            "church": {"name": "Synthetic Church"},
            "leadership": {"governing_body": {"members": ["Taylor Kim"]}},
        }), "")

    def test_leadership_print_opt_out_and_serving_role_allow_list(self) -> None:
        brand = {"church": {"name": "Synthetic"}, "leadership": {
            "print_in_bulletin": False,
            "clergy_and_staff": [{"role": "Pastor", "name": "Alex Reed"}],
        }}
        cfg = {"service": {"celebrant": "Alex Reed", "preacher": "Taylor Kim",
                            "serving": [{"role": "Reader", "name": "Morgan Lee"}]},
               "options": {"include_serving_today": True, "serving_roles": ["reader"]}}
        html = announcements_block(cfg, brand, Path("/tmp"))
        self.assertNotIn("Alex Reed", html)
        self.assertNotIn("Taylor Kim", html)
        self.assertIn("Morgan Lee", html)

    def test_variant_is_resolved_without_loading_plugin_order_files(self) -> None:
        cfg = {"liturgy": {"service_variant": {
            "id": "special",
            "name": "A Special Gathering",
            "base_service_plan": "episcopal-rite-ii",
            "replace": [{"unit": "peace", "with": "local-peace"}],
            "insert": [{"after": "peace", "units": ["silence"]}],
        }}}
        cfg["liturgy"]["service_plan"] = "episcopal-rite-ii"
        order = service_variant_order(cfg)
        self.assertEqual(order["replace"], {"peace": ["local-peace"]})
        self.assertEqual(order["insert"], {"peace": ["silence"]})

    def test_variants_apply_and_reject_unknown_anchors_for_both_plans(self) -> None:
        episcopal = {"liturgy": {"service_plan": "episcopal-rite-ii",
            "service_variant": {"id": "e", "name": "E", "base_service_plan": "episcopal-rite-ii",
                "replace": [{"unit": "peace", "with": "dismissal"}], "insert": []}}}
        html = liturgy_steps(service_variant_order(episcopal), "peace", {})
        self.assertIn("The Dismissal", html)
        lutheran = {"liturgy": {"service_plan": "lutheran-holy-communion",
            "service_variant": {"id": "l", "name": "L", "base_service_plan": "lutheran-holy-communion",
                "replace": [{"unit": "gathering", "with": "opening-acclamation"}], "insert": []}}}
        self.assertIn("The Opening Acclamation", liturgy_steps(
            service_variant_order(lutheran), "gathering", {}))
        for plan in ("episcopal-rite-ii", "lutheran-holy-communion"):
            bad = {"liturgy": {"service_plan": plan,
                "service_variant": {"id": "bad", "name": "Bad", "base_service_plan": plan,
                    "replace": [{"unit": "not-a-unit", "with": "peace"}], "insert": []}}}
            with self.assertRaises(ValueError):
                service_variant_order(bad)

    def test_footer_mapping_and_running_footer_are_separate_from_legacy_brand(self) -> None:
        brand = {"church": {"name": "Legacy Name", "address": "Old Address", "website": "old.example"},
                 "bulletin_footer": {"contact_name": "Bulletin Desk", "address": "New Address",
                                      "phone": "555-0100", "email": "desk@example.test", "website": "new.example"},
                 "colors": {}}
        line = footer_line(brand)
        self.assertIn("Bulletin Desk", line)
        self.assertIn("desk@example.test", line)
        self.assertNotIn("Legacy Name", line)
        css = build_css("classic", brand)
        self.assertIn("Bulletin Desk", css)
        for theme in ("classic", "modern"):
            theme_css = (Path(__file__).parents[1] / "skills" / "bulletin" / "renderer" / "themes" / f"{theme}.css").read_text()
            self.assertNotIn("@page back", theme_css)

    def test_qr_copy_requires_acceptance_or_complete_custom_copy(self) -> None:
        configured = {"qr": {"connect": "synthetic.png"}}
        self.assertIsNone(_qr_copy(configured))
        accepted = {"qr": {"standard_copy_accepted": True, "connect": "synthetic.png"}}
        self.assertEqual(_qr_copy(accepted)["connect_head"], "Connect with us")
        scaffold_blank = {"qr": {
            "standard_copy_accepted": True,
            "connect": "synthetic.png",
            "copy": {
                "heading": "",
                "connect_head": "",
                "give_head": "",
                "connect_body": "",
                "give_body": "",
            },
        }}
        resolved = _qr_copy(scaffold_blank)
        self.assertEqual(resolved["heading"], "Connect and Give")
        self.assertEqual(resolved["connect_head"], "Connect with us")
        custom = {"qr": {"connect": "synthetic.png", "copy": {
            "heading": "Visit", "connect_head": "Say hello", "connect_body": "Find us"}}}
        self.assertEqual(_qr_copy(custom)["connect_head"], "Say hello")

    def test_blessing_omit_staged_id_and_inline_text(self) -> None:
        brand = {"church": {"name": "Synthetic"}, "texts": {}}
        omitted = {"liturgy": {"blessing": "omit"}}
        self.assertEqual(blessing_block(omitted, brand, {}), "")
        staged = {"liturgy": {"blessing": "local-blessing", "files": {"local-blessing": "dismissal"}}}
        self.assertIn("The Blessing", blessing_block(
            staged, brand, {"liturgy_files": staged["liturgy"]["files"]}))
        inline = {"liturgy": {"blessing": "A private blessing."}}
        self.assertIn("A private blessing.", blessing_block(inline, brand, {}))

    def test_full_content_resolves_staged_communion_welcome_and_blessing(self) -> None:
        cfg = bulletin_input()
        cfg["liturgy"].update({
            "eucharistic_prayer": "A",
            "lords_prayer": "traditional",
            "prayers_of_the_people": "III",
            "blessing": "local-blessing",
            "communion_welcome": "local-welcome",
            "files": {
                "local-blessing": "dismissal",
                "communion_welcome": "peace",
            },
        })
        brand = {"church": {"name": "Synthetic Church"}, "colors": {}, "texts": {}}
        html = build_full_content(cfg, brand, Path("/tmp"), Path("/tmp"), "classic")
        self.assertNotIn("local-welcome", html)
        self.assertNotIn("local-blessing", html)
        self.assertIn("The Peace", html)
        self.assertIn("The Dismissal", html)
        self.assertNotIn("If you would rather not receive communion", html)

    def test_plain_private_communion_welcome_renders_as_rubric(self) -> None:
        with TemporaryDirectory() as temp_dir:
            liturgy_dir = Path(temp_dir)
            welcome_path = liturgy_dir / "local-welcome.md"
            welcome_path.write_text(
                "All are welcome at this table.\n",
                encoding="utf-8",
            )
            with patch.object(renderer, "LITURGY_DIR", liturgy_dir):
                html = renderer.render_blocks(
                    [("rubric", "[Communion welcome inserted here]")],
                    {
                        "communion_welcome": "local-welcome",
                        "liturgy_files": {"local-welcome": "local-welcome"},
                    },
                )

        self.assertIn(
            '<p class="rubric">All are welcome at this table.</p>',
            html,
        )
        self.assertNotIn('<p class="prose">', html)

    def test_inline_italics_are_rendered(self) -> None:
        self.assertEqual(inline_md("A *quiet* word"), "A <em>quiet</em> word")

    def test_merge_requires_printed_or_title_only_closing_and_empty_top(self) -> None:
        base = {"options": {"merge_back_page": True}}
        title_only = {"title": "A Sending"}
        printed = {"title": "A Song", "lyrics": [{"speaker": "All", "lines": ["Go in peace"]}]}
        image = {"title": "A Song", "images": ["song.png"]}
        self.assertTrue(can_merge_back_page(base, title_only,
                                            '<div class="backpage"><div class="bp-running">footer</div></div>'))
        self.assertTrue(can_merge_back_page(base, printed,
                                            '<div class="backpage"><div class="bp-running">footer</div></div>'))
        self.assertFalse(can_merge_back_page(base, image,
                                             '<div class="backpage"><div class="bp-running">footer</div></div>'))

    def test_dialogue_groups_keep_wrapped_text_in_their_text_column(self) -> None:
        css_path = (
            Path(__file__).parents[1]
            / "skills"
            / "bulletin"
            / "renderer"
            / "themes"
            / "base.css"
        )
        css = css_path.read_text()
        self.assertIn(
            ".dialogue-group .dialogue { display: table; }",
            css,
        )
        self.assertNotIn(
            ".dialogue-group .dialogue .line { display: inline; }",
            css,
        )

    def test_congregational_responses_are_bold_in_the_rendered_contract(self) -> None:
        css_path = (
            Path(__file__).parents[1]
            / "skills"
            / "bulletin"
            / "renderer"
            / "themes"
            / "base.css"
        )
        css = css_path.read_text()
        self.assertIn(
            ".dialogue.response .speaker,\n.dialogue.response .line { font-weight: 700; }",
            css,
        )
        self.assertIn(".psalm-response", css)
        psalm_rule = css.split(".psalm-response", 1)[1].split("}", 1)[0]
        self.assertIn("font-weight: 700;", psalm_rule)


if __name__ == "__main__":
    unittest.main()
