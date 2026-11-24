"""Behavior checks for native Xiaohongshu favorite note routes."""
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHELL = (ROOT.parent / "desktop-shell" / "Program.cs").read_text(encoding="utf-8")


def _script(name: str) -> str:
    match = re.search(
        rf'private const string {re.escape(name)} = @"(.*?)";',
        SHELL,
        re.DOTALL,
    )
    assert match, f"missing JavaScript script {name}"
    return match.group(1).replace('""', '"')


def test_native_profile_card_is_found_clicked_and_read_by_its_note_id():
    scripts = {
        "dom": _script("FavoriteNoteDomScript"),
        "action": _script("FavoriteNoteActionScript").replace("/*TARGET_ID*/", '"note42"').replace("/*RESET*/", "false"),
        "click": _script("ClickFavoriteNoteScript").replace("/*TARGET_ID*/", '"note42"'),
        "detail": _script("NoteDetailScript").replace("/*TARGET_ID*/", '"wrong42"'),
        "probe": _script("FavoriteNoteDetailVisibleScript"),
    }
    runner = r"""
const vm = require('node:vm');
const scripts = JSON.parse(process.argv[1]);
const exploreHref = '/explore/note42?xsec_token=explore&xsec_source=pc_collect';
const wrongProfileHref = '/user/profile/user17/wrong42?xsec_token=wrong&xsec_source=pc_collect';
const hiddenProfileHref = '/user/profile/user17/note42?xsec_token=hidden&xsec_source=pc_collect';
const profileHref = '/user/profile/user17/note42?xsec_token=private&xsec_source=pc_collect';
let clickedHref = '';
function makeAnchor(href, visible) {
  return {
    href: new URL(href, 'https://www.xiaohongshu.com').href,
    style: {display: 'block', visibility: visible ? 'visible' : 'hidden', opacity: '1'},
    getAttribute(name) { return name === 'href' ? href : null; },
    getBoundingClientRect() { return visible ? {width: 100, height: 40} : {width: 0, height: 0}; },
    click() { clicked += 1; clickedHref = href; }
  };
}
const anchors = [
  makeAnchor(exploreHref, true),
  makeAnchor(wrongProfileHref, true),
  makeAnchor(hiddenProfileHref, false),
  makeAnchor(profileHref, true)
];
let clicked = 0;
function matchesAnchor(anchor, selector) {
  return (selector.includes('/explore/') && anchor.href.includes('/explore/'))
    || (selector.includes('/user/profile/') && anchor.href.includes('/user/profile/'));
}
const card = {
  querySelector(selector) {
    if (selector.startsWith('a[')) {
      return anchors.find(anchor => selector.split(',').some(part => matchesAnchor(anchor, part))) || null;
    }
    if (selector.includes('title')) return {textContent: 'Saved title'};
    if (selector.includes('author') || selector.includes('.name')) return {textContent: 'Author'};
    return null;
  },
  querySelectorAll(selector) {
    if (selector.startsWith('a[')) {
      return anchors.filter(anchor => selector.split(',').some(part => matchesAnchor(anchor, part)));
    }
    return [];
  },
  scrollIntoView() {}
};
const detailNode = {textContent: 'Detail body', getBoundingClientRect() { return {width: 100, height: 20}; }};
const document = {
  scrollingElement: {scrollTop: 0, scrollHeight: 1000, clientHeight: 500},
  documentElement: {scrollTop: 0, scrollHeight: 1000, clientHeight: 500},
  body: {},
  querySelectorAll(selector) {
    return selector.includes('note-item') ? [card] : [];
  },
  querySelector(selector) {
    if (selector === '#detail-title' || selector === '#detail-desc') return detailNode;
    return null;
  }
};
const actualNote = {noteId: 'note42', title: 'Actual title', desc: 'Actual body', user: {nickname: 'Author'}, imageList: []};
const wrongNote = {noteId: 'wrong42', title: 'Wrong title', desc: 'Wrong body', user: {nickname: 'Wrong author'}, imageList: []};
const context = {
  document,
  location: {href: 'https://www.xiaohongshu.com/user/profile/user17/note42', pathname: '/user/profile/user17/note42'},
  window: {
    __INITIAL_STATE__: {note: {noteDetailMap: {note42: {note: actualNote}, wrong42: {note: wrongNote}}}},
    scrollTo() {}
  },
  URL,
  JSON,
  Array,
  String,
  Math,
  decodeURIComponent,
  getComputedStyle(node) { return node.style || {display: 'block', visibility: 'visible', opacity: '1'}; },
  scrollTo() {},
};
function run(source) { return vm.runInNewContext(source, context); }
function parse(source) {
  const result = run(source);
  return typeof result === 'string' ? JSON.parse(result) : result;
}
const dom = parse(scripts.dom);
const action = parse(scripts.action);
const click = parse(scripts.click);
const detail = parse(scripts.detail);
const probe = parse(scripts.probe);
    console.log(JSON.stringify({dom, action, click, detail, probe, clicked, clickedHref}));
"""
    result = subprocess.run(
        ["node", "-e", runner, json.dumps(scripts)],
        check=True,
        capture_output=True,
        text=True,
    )
    observed = json.loads(result.stdout)

    assert observed["dom"][0]["id"] == "note42"
    assert observed["dom"][0]["routeType"] == "profile"
    assert observed["dom"][0]["href"] == "/user/profile/user17/note42?xsec_token=private&xsec_source=pc_collect"
    assert observed["action"]["found"] is True
    assert observed["action"]["routeType"] == "profile"
    assert observed["click"] == {"clicked": True, "routeType": "profile", "noteId": "note42"}
    assert observed["clicked"] == 1
    assert observed["clickedHref"] == "/user/profile/user17/note42?xsec_token=private&xsec_source=pc_collect"
    assert observed["detail"]["id"] == "note42"
    assert observed["probe"]["routeType"] == "profile"
    assert observed["probe"]["routeId"] == "note42"


def test_visible_dialog_with_app_qr_prompt_is_recognized_without_phone_word():
    script = _script("FavoriteNoteDetailVisibleScript")
    runner = r"""
const vm = require('node:vm');
const script = JSON.parse(process.argv[1]);
const prompt = {
  innerText: '请打开小红书App扫码查看',
  getBoundingClientRect() { return {width: 240, height: 180}; }
};
const document = {
  querySelectorAll(selector) { return selector.includes('[role=dialog]') ? [prompt] : []; },
  querySelector() { return null; }
};
const context = {
  document,
  location: {pathname: '/explore/note42'},
  URL,
  decodeURIComponent,
  getComputedStyle() { return {display: 'block', visibility: 'visible', opacity: '1'}; }
};
console.log(JSON.stringify(vm.runInNewContext(script, context)));
"""
    result = subprocess.run(
        ["node", "-e", runner, json.dumps(script)],
        check=True,
        capture_output=True,
        text=True,
    )
    observed = json.loads(result.stdout)

    assert observed["phoneQrPrompt"] is True
    assert observed["visible"] is False


def test_profile_route_is_validated_and_route_diagnostics_exclude_url_parameters():
    read = SHELL.split("public async Task<XhsSessionResult> ReadNoteAsync(", 1)[1].split(
        "private async Task<bool> EnsureFavoriteCollectionAsync(", 1
    )[0]
    dom_reader = SHELL.split("private async Task<List<XhsFavoriteCandidate>> ReadFavoriteNotesFromDomAsync(", 1)[1].split(
        "private void MergeFavoriteCandidates(", 1
    )[0]
    open_note = SHELL.split("private async Task<string> OpenFavoriteNoteAsync(", 1)[1].split(
        "private async Task<string> CaptureFavoriteListStateAsync(", 1
    )[0]

    assert "TryGetXhsNoteRoute(target" in read
    assert "TryGetXhsNoteRoute(resolved" in dom_reader
    assert "event=card_click path_type=" in open_note
    assert "note_id=" in open_note
    assert "target.Query" not in open_note
    assert "resolved.Query" not in dom_reader
