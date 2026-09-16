"""Audit area 9 — i18n / RTL.

The frontend has no build step and no test runner of its own, so these
checks are done here by parsing `js/i18n.js` directly. They guard the two
failure modes that actually bite this bilingual app:

  1. A key used by a page but missing from the dictionary. `t()` falls back
     to returning the key itself, so the UI silently renders raw identifiers
     like "deadline_confirm" to a lawyer instead of real text.
  2. A key present in Arabic but missing from English (or vice versa).
     `t()` falls back to the Arabic entry, so an English-language user
     silently gets Arabic text in the middle of an English screen.

Neither throws, neither shows up in any log, and both are invisible until a
user reports it — exactly what an automated check is for.
"""

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
I18N = PROJECT_ROOT / "js" / "i18n.js"
PAGES = sorted((PROJECT_ROOT / "js").rglob("*.js"))

# Keys assembled at runtime from a prefix plus a variable, e.g.
# t("stage_" + c.stage). The static scan can't resolve these, so each
# prefix is expanded here against the values the code can actually produce.
DYNAMIC_KEY_FAMILIES = {
    "stage_": ["new", "prep", "pleading", "judgment", "execution", "closed"],
    "role_": ["Admin", "Lawyer", "consultant", "delegate", "User"],
    "proc_tier_": ["official_verified", "official_inferred", "firm_entered", "ai_suggested", "unverified"],
    "proc_confidence_": ["confirmed", "provisional"],
    "deadline_status_": ["open", "met", "missed", "waived"],
}


def _dict_blocks() -> tuple[set[str], set[str]]:
    text = I18N.read_text(encoding="utf-8")
    ar_part, en_part = text.split("en: {", 1)
    # Match the KEY only, not the start of its value. Values in this file
    # legitimately appear single-quoted, double-quoted (whenever the text
    # contains an apostrophe, e.g. "Today's Hearings"), or wrapped onto the
    # following line when long -- an earlier, stricter version of this regex
    # required `:\s*'` on the same line and therefore reported six perfectly
    # translated keys as missing.
    key_re = r"^\s{4}([a-zA-Z0-9_]+):"
    return (
        set(re.findall(key_re, ar_part, re.M)),
        set(re.findall(key_re, en_part, re.M)),
    )


def _used_keys() -> set[str]:
    used: set[str] = set()
    # The lookbehind matters: without it, `t("div")` matches inside
    # `createElement("div")` and the scan reports phantom missing keys.
    call_re = r"""(?<![A-Za-z0-9_$.])t\(\s*["']([a-zA-Z0-9_]+)["']\s*\)"""
    concat_re = r"""(?<![A-Za-z0-9_$.])t\(\s*["']([a-zA-Z0-9_]+)["']\s*\+"""
    for path in PAGES:
        if path.name == "i18n.js":
            continue
        src = path.read_text(encoding="utf-8")
        used |= set(re.findall(call_re, src))
        for prefix in re.findall(concat_re, src):
            for suffix in DYNAMIC_KEY_FAMILIES.get(prefix, []):
                used.add(prefix + suffix)
    return used


def test_arabic_and_english_dictionaries_have_identical_key_sets():
    ar_keys, en_keys = _dict_blocks()
    missing_from_en = sorted(ar_keys - en_keys)
    missing_from_ar = sorted(en_keys - ar_keys)
    assert not missing_from_en, (
        "Keys defined in Arabic but not English — an English user silently "
        f"sees Arabic text for these: {missing_from_en}"
    )
    assert not missing_from_ar, (
        f"Keys defined in English but not Arabic: {missing_from_ar}"
    )


def test_every_translation_key_used_by_a_page_actually_exists():
    ar_keys, _ = _dict_blocks()
    unknown = sorted(k for k in _used_keys() if k not in ar_keys)
    assert not unknown, (
        "Pages call t() with keys that are not in the dictionary — these "
        f"render as raw identifiers in the UI: {unknown}"
    )


def test_html_shell_declares_rtl_and_arabic_as_the_default():
    """The app boots Arabic-first (localStorage 'aslg_lang' defaults to
    'ar'), so the served HTML must already be dir=rtl before any JS runs —
    otherwise the first paint is LTR and visibly flips."""
    html = (PROJECT_ROOT / "index.html").read_text(encoding="utf-8")
    assert re.search(r'<html[^>]*lang="ar"', html)
    assert re.search(r'<html[^>]*dir="rtl"', html)


def test_language_toggle_updates_both_dir_and_lang_attributes():
    """applyLangToDocument must set BOTH attributes. Setting `dir` alone
    mirrors the layout but leaves screen readers and font selection on the
    wrong language; setting `lang` alone leaves the layout unmirrored."""
    src = I18N.read_text(encoding="utf-8")
    fn = src.split("export function applyLangToDocument")[1]
    assert "dir" in fn and "lang" in fn
