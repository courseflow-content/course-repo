"""Assemble a candidate's revision digest.

Revision content is never authored twice. It lives in exactly two places:

  circle 1  the `## 🔁 Revise` block at the top of each shared skill lesson
  circle 2  the candidate's own [FILL] answers, ledger and metric vault

This script finds which skill lessons the candidate's chapters reference, pulls
those blocks, staples the candidate's own material to the front, and writes one
generated file. Re-run it whenever either side changes.

    python build_revision_digest.py <candidate-repo> [--mode revise|rehearse]

`--mode rehearse` produces the 48-hour version: rapid-fire blocks only.
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

REVISE_HEADING = "## 🔁 Revise"
REHEARSE_HEADING = "## 🔷 Rehearse"
REF = re.compile(r"(skill\.[a-z0-9-]+)#([a-z0-9-]+)")


def read(p):
    return open(p, encoding="utf-8").read()


LINK = re.compile(r"\]\((?!https?:|#)([^)#]+)(#[^)]*)?\)")


def rebase_links(text, src_path, out_dir):
    """Extracted content moves into revision/, so every relative link must be rebased
    against the directory the digest is written to. Without this the digest is full of
    links that resolved perfectly in their source file and resolve nowhere here."""
    src_dir = os.path.dirname(src_path)

    def fix(m):
        target, frag = m.group(1), m.group(2) or ""
        abs_t = os.path.normpath(os.path.join(src_dir, target))
        if not os.path.exists(abs_t):
            return m.group(0)                      # leave unresolvable targets untouched
        rel = os.path.relpath(abs_t, out_dir).replace(os.sep, "/")
        return f"]({rel}{frag})"

    return LINK.sub(fix, text)


def extract_section(text, heading_startswith):
    """Everything from a heading up to the next same-or-higher-level heading."""
    lines = text.split("\n")
    out, capturing = [], False
    for ln in lines:
        if ln.startswith(heading_startswith):
            capturing = True
            continue
        if capturing and re.match(r"^#{1,2} ", ln):
            break
        if capturing:
            out.append(ln)
    return "\n".join(out).strip("\n-— \t")


def skill_courses():
    """course_id -> (repo_dir, metadata)"""
    found = {}
    for name in sorted(os.listdir(REPO_ROOT)):
        p = os.path.join(REPO_ROOT, name, "metadata.json")
        if not os.path.isfile(p):
            continue
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        if d.get("archetype") == "skill-course" and "course_id" in d:
            found[d["course_id"]] = (name, d)
    return found


def lesson_index(meta):
    """lesson_key -> lesson dict"""
    return {l["lesson_key"]: l
            for m in meta.get("curriculum", []) for l in m["lessons"]
            if "lesson_key" in l}


def candidate_refs(cand_dir):
    """Ordered, de-duplicated (course_id, lesson_key) references across the chapters."""
    refs, seen = [], set()
    for root, _, files in os.walk(cand_dir):
        if os.path.basename(root) == "revision":
            continue
        for f in sorted(files):
            if not f.endswith(".md"):
                continue
            for cid, key in REF.findall(read(os.path.join(root, f))):
                if (cid, key) not in seen:
                    seen.add((cid, key))
                    refs.append((cid, key, os.path.relpath(os.path.join(root, f), cand_dir)))
    return refs


def register(cand_dir, out_path, mode, only, title=None):
    """Generated content must register itself, or the portal never shows it.

    Adding entries by hand defeats the point: a card produced by a script and
    listed by a human drifts the moment either side changes.
    """
    meta_p = os.path.join(cand_dir, "metadata.json")
    if not os.path.isfile(meta_p):
        return None
    meta = json.load(open(meta_p, encoding="utf-8"))
    rel = os.path.relpath(out_path, cand_dir).replace(os.sep, "/")
    lid = "rev_" + re.sub(r"[^a-z0-9]+", "_", rel.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower())
    label = {"revise": "Revise", "rehearse": "Rehearse"}[mode]
    name = f"{label} — {title}" if only else f"Full {label} Digest"

    mod = next((m for m in meta["curriculum"] if m["module_id"] == "module_revision"), None)
    if mod is None:
        mod = {"module_id": "module_revision",
               "title": "Revision — generated, do not edit",
               "lessons": []}
        meta["curriculum"].append(mod)

    entry = {"id": lid, "title": name, "defaultMode": "mdx",
             "generated": True, "modes": {"mdx": rel}}
    existing = next((l for l in mod["lessons"] if l["id"] == lid), None)
    if existing:
        existing.update(entry)
    else:
        mod["lessons"].append(entry)

    # digests first, then topic cards alphabetically - stable order across rebuilds
    mod["lessons"].sort(key=lambda l: (("--only" in l["modes"]["mdx"]) or "digest" not in l["modes"]["mdx"],
                                       l["title"]))
    meta["modules"] = len(meta["curriculum"])
    meta["lessons"] = sum(len(m["lessons"]) for m in meta["curriculum"])
    json.dump(meta, open(meta_p, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    return name


def build(cand_dir, mode="revise", only=None):
    heading = REVISE_HEADING if mode == "revise" else REHEARSE_HEADING
    courses = skill_courses()
    refs = candidate_refs(cand_dir)
    if only:
        refs = [r for r in refs if r[1] == only]

    own, fills = [], 0
    for rel, wanted in [("PROGRESS.md", ["## 🟢 Defensibility Ledger", "## 🟢 Metric Vault"]),
                        ("defence/01_qlora_finetune.md",
                         ["## 🔷 What Is Yours to Defend", "## 🔷 The Five Follow-Ups"])]:
        p = os.path.join(cand_dir, rel)
        if not os.path.exists(p):
            continue
        txt = read(p)
        for h in wanted:
            sec = extract_section(txt, h)
            if sec:
                sec = rebase_links(sec, p, os.path.join(cand_dir, "revision"))
                own.append((h.split("· ")[-1].lstrip("# 🟢🔷 "), rel, sec))
                fills += len(re.findall(r"\[FILL[^\]]*\]", sec))

    if only:
        label = {"revise": "Revise", "rehearse": "Rehearse"}[mode]
        mins = {"revise": 8, "rehearse": 3}[mode]
        title = next((courses[c][1] and lesson_index(courses[c][1]).get(k, {}).get("title")
                      for c, k, _ in refs if k == only), only)
        parts = [
            f"# {label} — {title}",
            "",
            f"> ⚠️ **Generated. Do not edit.**  `build_revision_digest.py "
            f"{os.path.basename(cand_dir)} --mode {mode} --only {only}`",
            ">",
            f"> Pulled from the lesson's single `## 🔁 {label}` source. About {mins} minutes.",
            "",
            "---",
            "",
        ]
        own = []
    else:
        parts = [
            f"# Revision Digest — {mode}",
            "",
            "> ⚠️ **Generated file. Do not edit.**  Rebuild with "
            f"`python course-repo/tools/build_revision_digest.py {os.path.basename(cand_dir)} --mode {mode}`",
            ">",
            "> Every section below is pulled from its single source — the skill lessons and your own"
            " tracker. Editing here creates a second copy that will drift.",
            "",
            f"**Unresolved `[FILL]` slots in your own material: {fills}.** "
            + ("Revision cannot substitute for recovering these — they are what you will actually be asked."
               if fills else "Nothing outstanding."),
            "",
            "---",
            "",
            "## Part 1 — Your own material",
            "",
            "*This is the larger half. An interviewer asks what **your** parameter count was, not what"
            " quantile spacing is in the abstract.*",
            "",
        ]
    for title_, src, sec in own:
        parts += [f"### {title_}", f"*source: `{src}`*", "", sec, ""]

    if not only:
        parts += ["---", "", f"## Part 2 — Mechanism ({mode} blocks from the shared lessons)", ""]
    if not refs:
        parts += ["*No skill-lesson references found in this candidate's chapters.*", ""]

    written = stubs = missing = 0
    resolved_title = None
    for cid, key, src in refs:
        if cid not in courses:
            parts += [f"### ⚠️ `{cid}#{key}` — course not found", ""]
            missing += 1
            continue
        repo, meta = courses[cid]
        les = lesson_index(meta).get(key)
        if not les:
            parts += [f"### ⚠️ `{cid}#{key}` — lesson id not in that course's manifest", ""]
            missing += 1
            continue
        title = les["title"]
        if les.get("status") == "stub":
            parts += [f"### 🚧 {title}", f"*`{cid}#{key}` · referenced by `{src}` · **not yet written***",
                      "", "> No revision content exists for this lesson yet. This gap is real —"
                      " it is not silently omitted.", ""]
            stubs += 1
            continue
        path = os.path.join(REPO_ROOT, repo, les["modes"]["mdx"])
        sec = extract_section(read(path), heading)
        sec = rebase_links(sec, path, os.path.join(cand_dir, "revision"))
        if only:
            rel = os.path.relpath(path, os.path.join(cand_dir, "revision")).replace(os.sep, "/")
            sec = sec.replace("](#rehearse)", f"]({rel}#rehearse)")
        if not sec:
            parts += [f"### ⚠️ {title}", f"*no `{heading}` section found in the lesson*", ""]
            missing += 1
            continue
        link = os.path.relpath(path, os.path.join(cand_dir, "revision")).replace(os.sep, "/")
        head = [] if only else [f"### {title}"]
        parts += head + [f"*`{cid}#{key}` · {les.get('est_minutes','?')} min for the full lesson · "
                         f"[open it]({link})*", "", sec, ""]
        written += 1
        resolved_title = title

    if not only:
        parts += ["---", "",
                  f"**Coverage:** {written} lesson(s) with content · {stubs} stub(s) · {missing} unresolved."]
    if stubs:
        parts.append(f"\n⚠️ {stubs} referenced lesson(s) have no content yet. Writing them is the "
                     "highest-value gap in this digest.")

    out_dir = os.path.join(cand_dir, "revision")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"{mode}-{only}.md" if only else f"digest-{mode}.md")
    open(out, "w", encoding="utf-8").write("\n".join(parts) + "\n")
    registered = register(cand_dir, out, mode, only, resolved_title)
    return out, dict(registered=registered, written=written, stubs=stubs,
                     missing=missing, fills=fills, refs=len(refs))


if __name__ == "__main__":
    cand = sys.argv[1] if len(sys.argv) > 1 else "Laksh-Seth-Interview-Readiness"
    mode = "revise"
    only = None
    if "--mode" in sys.argv:
        mode = sys.argv[sys.argv.index("--mode") + 1]
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]
    cand_dir = cand if os.path.isabs(cand) else os.path.join(REPO_ROOT, cand)
    out, stats = build(cand_dir, mode, only)
    print(f"wrote {os.path.relpath(out, REPO_ROOT)}")
    print(f"  references found : {stats['refs']}")
    print(f"  with content     : {stats['written']}")
    print(f"  stubs (gaps)     : {stats['stubs']}")
    print(f"  unresolved       : {stats['missing']}")
    print(f"  your [FILL] slots: {stats['fills']}")
    print(f"  portal entry     : {stats['registered'] or 'NOT REGISTERED'}")
