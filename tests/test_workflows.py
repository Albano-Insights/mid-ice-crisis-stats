"""Every workflow and issue form has to parse.

A workflow with a YAML error doesn't fail loudly: GitHub reports a zero-second "failure" against
whatever push touched it and the trigger it was written for simply never fires again. That is how
the roster-add workflow shipped broken -- a `\n` in a github-script body had become a real
newline, splitting a JS string across two lines. The issue forms matter the same way: the
processors map a submission back to its fields by label, so a form that won't parse takes its
whole path down with it.

Run: python -m pytest
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
FORMS = sorted((ROOT / ".github" / "ISSUE_TEMPLATE").glob("*.yml"))


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_parses_and_has_a_trigger(path: Path):
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert doc.get("jobs"), f"{path.name} declares no jobs"
    # PyYAML reads the bare key `on` as the boolean True, which is why this looks odd.
    assert doc.get("on") or doc.get(True), f"{path.name} declares no trigger"


@pytest.mark.parametrize("path", FORMS, ids=lambda p: p.name)
def test_issue_form_parses(path: Path):
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert doc.get("body"), f"{path.name} has no body"
    assert doc.get("labels"), f"{path.name} applies no label, so no workflow will pick it up"


def test_every_issue_form_label_has_a_workflow_waiting_for_it():
    """The label is the contract between a form and its processor. GitHub does not create a label
    an issue template asks for, so the label also has to exist in the repo -- checked by hand with
    `gh label list`, not here."""
    labels = {lbl for path in FORMS for lbl in yaml.safe_load(path.read_text(encoding="utf-8"))["labels"]}
    watched = set()
    for path in WORKFLOWS:
        text = path.read_text(encoding="utf-8")
        for lbl in labels:
            if f"'{lbl}'" in text or f'"{lbl}"' in text:
                watched.add(lbl)
    assert labels <= watched, f"no workflow reacts to {labels - watched}"
