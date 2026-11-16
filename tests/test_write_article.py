"""The article command line — `write_article.py` (ADR 0005, item 7).

A thin shell over `article.pipeline`. Offline: the model is replaced at
`ask.call_model`, the embeddings by the offline fake.
"""

from __future__ import annotations

import dataclasses
import io
import json
from pathlib import Path

import pytest

import ask
import write_article
from article import assemble, pipeline
from test_article import BRIEFS, SCRIPT, Scripted, payload, trial  # noqa: F401  (trial is a fixture)
from test_article_quality import Dying, Restart

ROOT = Path(ask.__file__).resolve().parent


@pytest.fixture
def cli(trial, tmp_path, monkeypatch):
    outline = tmp_path / "outline.txt"
    outline.write_text("# FIXTURE outline\n" + "\n".join(f"FIXTURE heading {n + 1} | {b}" for n, b in enumerate(BRIEFS)),
                       encoding="utf-8")

    class Cli:
        out = tmp_path / "articles"
        model = Scripted(SCRIPT)
        outline_file = outline

        def run(self, *args, model=None):
            self.model = model or Scripted(SCRIPT)
            monkeypatch.setattr(ask, "call_model", self.model)
            stream = io.StringIO()
            self.code = write_article.main([*args, "--out-dir", str(self.out)], stream)
            self.text = stream.getvalue()
            return self

        def new(self, *args, **kwargs):
            return self.run("--title", "FIXTURE harbour title", "--outline", str(outline), *args, **kwargs)

        def record(self) -> dict:
            (path,) = self.out.glob("*/record.json")
            return json.loads(path.read_text(encoding="utf-8"))

    return Cli()


def test_a_dry_run_prints_the_planned_calls_and_sends_nothing(cli, monkeypatch):
    monkeypatch.setattr(ask, "embed_texts", lambda *a, **k: pytest.fail("a dry run embedded something"))
    run = cli.new("--editorial", "--frame", "generate", "--dry-run")

    assert run.code == 0 and run.model.calls == [] and not cli.out.exists()
    for line in ("sections                     3", "editorial rewrites, at most  3", "introduction                 1",
                 "transitions, at most         2", "conclusion                   1", "model calls in all           10",
                 "embedding calls              3"):
        assert line in run.text
    assert "No price is configured (LLM_PRICE_INPUT_PER_MTOK, LLM_PRICE_OUTPUT_PER_MTOK), so no cost is shown." in run.text
    assert "$" not in run.text                                          # a price is never assumed


def test_a_dry_run_shows_a_cost_only_from_configured_prices(cli, monkeypatch):
    monkeypatch.setattr(ask, "settings", dataclasses.replace(
        ask.settings, llm_price_input_per_mtok=1.0, llm_price_output_per_mtok=5.0))
    workspace = pipeline.open_workspace()
    numbers = write_article.estimate(workspace, pipeline.new_draft("FIXTURE t", [("FIXTURE h", b) for b in BRIEFS]))
    run = cli.new("--dry-run")

    expected = (numbers["input_tokens_upper_estimate"] * 1.0 + numbers["output_tokens_upper_bound"] * 5.0) / 1_000_000
    assert numbers["model_calls"] == 3 and numbers["output_tokens_upper_bound"] == 3 * ask.settings.llm_max_tokens
    assert numbers["cost_upper_estimate_usd"] == round(expected, 4) > 0
    assert f"cost, upper estimate         ${expected:.4f}" in run.text


def test_the_command_line_writes_the_same_record_as_the_view(cli):
    run = cli.new()
    record = cli.record()

    assert run.code == 0 and len(run.model.calls) == 3
    assert record["schema_version"] == pipeline.SCHEMA_VERSION and record["status"] == "draft"
    assert record["plan"] == {"frame": {"introduction": "none", "transitions": "none", "conclusion": "none"},
                              "editorial": False, "voice_exemplar": ""}
    assert [s["heading"] for s in record["sections"]] == ["FIXTURE heading 1", "FIXTURE heading 2", "FIXTURE heading 3"]
    assert record["commentary_switched_on"] is False and record["frame"]["introduction"] is None
    assert run.text.count("  saved: section") == 3 and "saved: finished" in run.text
    assert "Notes to check in the web app: 3." in run.text
    assert "connectives_per_1000_words:" in run.text and "(target at least 12.0)" in run.text
    assert assemble.COMMENTARY_LABEL not in next(cli.out.glob("*/article.md")).read_text(encoding="utf-8")


def test_the_switches_reach_the_plan(cli, tmp_path):
    mine = tmp_path / "intro.md"
    mine.write_text("FIXTURE my own opening words.", encoding="utf-8")
    run = cli.new("--editorial", "--commentary", "--frame", "generate", "--introduction-file", str(mine))
    record = cli.record()

    assert record["plan"] == {"frame": {"introduction": "researcher", "transitions": "generated",
                                        "conclusion": "generated"}, "editorial": True, "voice_exemplar": ""}
    assert record["commentary_switched_on"] is True
    assert record["frame"]["introduction"] == {"origin": "researcher", "text": "FIXTURE my own opening words."}
    assert len(run.model.calls) == 3 + 3 + 2 + 1                        # sections, rewrites, transitions, conclusion
    assert "EDITORIAL PASS" in run.text and run.text.count("rewrite kept") == 3


def test_an_interrupted_draft_is_listed_and_resumed_from_the_command_line(cli):
    with pytest.raises(Restart):
        cli.new(model=Dying(at=3))
    article_id = cli.record()["article_id"]

    listed = cli.run("--list")
    assert f"{article_id}  unfinished, 1 model call(s) left  FIXTURE harbour title" in listed.text

    resumed = cli.run("--resume", article_id)
    assert [question for question, _, _ in resumed.model.calls] == [BRIEFS[2]]
    assert "(already drafted)" in resumed.text and resumed.code == 0
    assert cli.record()["status"] == "draft"
    assert cli.run("--resume", "no-such-article").code == 2


def test_an_earlier_articles_record_gives_the_title_and_outline(cli):
    first = cli.new()
    (earlier,) = cli.out.glob("*/record.json")

    again = cli.run("--from-record", str(earlier), "--editorial", "--dry-run")

    assert again.code == 0 and "Title   : FIXTURE harbour title" in again.text
    assert "  3. FIXTURE heading 3" in again.text and "model calls in all           6" in again.text
    assert first.code == 0 and again.model.calls == []


def test_a_bad_outline_or_a_missing_file_stops_before_any_call(cli, tmp_path):
    short = tmp_path / "short.txt"
    short.write_text("FIXTURE one | FIXTURE q?\nFIXTURE two | FIXTURE q?", encoding="utf-8")

    assert cli.run("--title", "FIXTURE t", "--outline", str(short)).code == 2
    assert "An outline has 3 to 6 sections; this one has 2." in cli.text
    assert cli.run("--title", "FIXTURE t", "--outline", str(tmp_path / "none.txt")).code == 2
    assert "No such file" in cli.text and cli.model.calls == [] and not cli.out.exists()


def test_a_blocked_section_is_reported_with_its_reason_and_exit_code_one(cli):
    run = cli.new(model=Scripted({**SCRIPT, "orchard": payload("[E1] states that rootstock is listed.", cites=["E1"])}))

    assert run.code == 1
    assert "section: FIXTURE heading 2: article check failed: handle_used_as_subject" in run.text


def test_the_command_line_is_a_shell_with_no_drafting_of_its_own():
    source = (ROOT / "write_article.py").read_text(encoding="utf-8")

    for forbidden in ("run_query", "call_model", "draft_from_evidence", "draft_section(", "validate("):
        assert forbidden not in source, forbidden
    assert "pipeline.run(" in source


def test_em_dashes_left_in_print_are_reported_on_the_command_line(cli):
    run = cli.new(model=Scripted({**SCRIPT, "orchard": payload("FIXTURE the calendar—an old one—lists rootstock [E1].", cites=["E1"])}))

    assert run.code == 0
    assert "EM DASHES: “FIXTURE heading 2” prints 2 (target 0). They are left as written" in run.text


def test_a_combined_handle_is_reported_as_a_blocked_section_on_the_command_line(cli):
    run = cli.new(model=Scripted({**SCRIPT, "orchard": payload("FIXTURE the calendar lists rootstock [E1, E2].", cites=["E1", "E2"])}))
    (article,) = cli.out.glob("*/article.md")

    assert run.code == 1 and "section: FIXTURE heading 2: validation failed: malformed_handle" in run.text
    assert "[E" not in article.read_text(encoding="utf-8")


def test_the_command_line_exports_a_reviewed_article_and_refuses_an_unreviewed_one(cli):
    cli.new()
    article_id = cli.record()["article_id"]
    refused = cli.run("--export", article_id)
    assert refused.code == 1 and "cannot be exported yet: 3 of 3 sentences are not judged yet" in refused.text
    assert not list(cli.out.glob("*/medium.md"))

    workspace = pipeline.open_workspace()
    draft = pipeline.load(cli.out / article_id, workspace)
    for pair in pipeline.render(workspace, draft).pairs:
        pipeline.set_pair_verdict(draft, pair, "supports")
    pipeline.save(workspace, draft, cli.out)

    done = cli.run("--export", article_id)
    exported = (cli.out / article_id / "medium.md").read_text(encoding="utf-8")
    assert done.code == 0 and done.model.calls == []                    # no model call to export
    assert exported.splitlines()[2].startswith("This article was drafted with an AI system") and "DRAFT" not in exported
    assert (cli.out / article_id / "medium.html").read_text(encoding="utf-8").startswith("<h1>FIXTURE harbour title</h1>")
    assert cli.run("--export", "no-such-article").code == 2


def test_the_dry_run_prints_the_retrieval_preview_when_asked_and_still_calls_no_model(cli, monkeypatch):
    embedded, embed = [], ask.embed_texts
    monkeypatch.setattr(ask, "embed_texts", lambda texts, **kw: embedded.append(texts) or embed(texts, **kw))
    plain = cli.new("--dry-run")
    assert embedded == [] and "RETRIEVAL PREVIEW" not in plain.text      # a plain dry run still sends nothing

    run = cli.new("--dry-run", "--preview")
    assert run.model.calls == [] and len(embedded) == 3 and not cli.out.exists()
    assert "RETRIEVAL PREVIEW (embedding only; scores are diagnostics, not confidence)" in run.text
    assert f"  1. {BRIEFS[0]}" in run.text and "p. 3 " in run.text


def test_a_voice_example_file_reaches_the_editorial_pass_from_the_command_line(cli, tmp_path):
    mine = tmp_path / "mine.md"
    mine.write_text("FIXTURE I walked the quay at dusk. But the lamps were not yet lit.", encoding="utf-8")
    run = cli.new("--editorial", "--voice-example", str(mine))

    assert cli.record()["plan"]["voice_exemplar"].startswith("FIXTURE I walked the quay")
    assert sum(1 for i in run.model.instructions if i and "VOICE EXAMPLE" in i) == 3       # each rewrite, and only those
    assert cli.run("--title", "FIXTURE t", "--outline", str(cli.outline_file), "--voice-example", str(tmp_path / "no.md")).code == 2
