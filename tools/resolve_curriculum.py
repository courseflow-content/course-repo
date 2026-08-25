"""Resolve a candidate's résumé skills into an ordered course plan.

Courses are functions: `signature.requires` are the parameters, `signature.provides`
is the return value. This resolves the call graph.

    parse    → normalise free-text résumé terms against the skill registry
    closure  → add prerequisite skills transitively
    resolve  → find the course that provides each skill
    missing  → skills with no provider are the courses to generate
    order    → topological sort over requires

Run:  python resolve_curriculum.py <candidate_skills.json>
      python resolve_curriculum.py --demo
"""

import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
REGISTRY = os.path.join(HERE, "..", "config", "skill-registry.json")


# ---------------------------------------------------------------- registry

def load_registry():
    reg = json.load(open(REGISTRY, encoding="utf-8"))["skills"]
    alias = {}
    for sid, s in reg.items():
        alias[sid.lower()] = sid
        alias[s["label"].lower()] = sid
        for a in s.get("aliases", []):
            alias[a.lower()] = sid
    return reg, alias


def normalise(terms, alias):
    """Free text off a résumé -> canonical skill ids. Unmatched terms are reported."""
    hits, misses = [], []
    for t in terms:
        key = t.strip().lower()
        (hits if key in alias else misses).append(alias.get(key, t))
    return sorted(set(hits)), sorted(set(misses))


def closure(skills, reg):
    """Add prerequisite skills transitively. This is what makes ordering computable."""
    seen, stack = set(), list(skills)
    while stack:
        s = stack.pop()
        if s in seen or s not in reg:
            continue
        seen.add(s)
        stack.extend(reg[s].get("requires", []))
    return seen


# ---------------------------------------------------------------- courses

def load_courses():
    """Every metadata.json in local-courses-repo that declares a signature."""
    courses = []
    for name in sorted(os.listdir(REPO_ROOT)):
        p = os.path.join(REPO_ROOT, name, "metadata.json")
        if not os.path.isfile(p):
            continue
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        if "signature" in d:
            courses.append(d)
    return courses


def provider_index(courses):
    idx = {}
    for c in courses:
        for s in c["signature"].get("provides", []):
            idx.setdefault(s, []).append(c["course_id"])
    return idx


def topo_sort(course_ids, courses_by_id, provides_by_course):
    """Order courses so that a course's required skills are provided before it."""
    skill_owner = {s: cid for cid, ss in provides_by_course.items() for s in ss}
    edges = defaultdict(set)
    for cid in course_ids:
        for req in courses_by_id[cid]["signature"].get("requires", []):
            owner = skill_owner.get(req)
            if owner and owner != cid and owner in course_ids:
                edges[cid].add(owner)
    ordered, seen, temp = [], set(), set()

    def visit(c):
        if c in seen:
            return
        if c in temp:                       # cycle: report rather than hang
            ordered.append(f"!! cycle at {c}")
            return
        temp.add(c)
        for dep in sorted(edges[c]):
            visit(dep)
        temp.discard(c)
        seen.add(c)
        ordered.append(c)

    for c in sorted(course_ids):
        visit(c)
    return ordered


# ---------------------------------------------------------------- report

def resolve(resume_terms, verbose=True):
    reg, alias = load_registry()
    claimed, unmatched = normalise(resume_terms, alias)
    required = closure(claimed, reg)

    courses = load_courses()
    by_id = {c["course_id"]: c for c in courses}
    provides = {c["course_id"]: c["signature"].get("provides", []) for c in courses}
    idx = provider_index(courses)

    covered, missing = {}, []
    for s in sorted(required):
        if s in idx:
            covered.setdefault(idx[s][0], []).append(s)
        else:
            missing.append(s)

    order = topo_sort(set(covered), by_id, provides)

    if verbose:
        print("=" * 72)
        print("RESUME -> CURRICULUM")
        print("=" * 72)
        print(f"\nclaimed on the résumé ({len(claimed)}): {', '.join(claimed)}")
        if unmatched:
            print(f"\n⚠ unmatched terms (not in the registry): {', '.join(unmatched)}")
            print("  → either add them to the registry or they are not skills we teach")
        print(f"\nwith prerequisites, {len(required)} skills are required")

        print("\n" + "-" * 72)
        print("COVERED — courses that exist, in dependency order")
        print("-" * 72)
        for i, cid in enumerate(order, 1):
            c = by_id.get(cid)
            if not c:
                print(f"  {i}. {cid}")
                continue
            reqs = ", ".join(c["signature"].get("requires", [])) or "none"
            print(f"  {i}. {cid:32s} {c['title']}")
            print(f"     provides: {', '.join(sorted(covered[cid]))}")
            print(f"     requires: {reqs}")

        print("\n" + "-" * 72)
        print("MISSING — no course provides these. Each is a course to generate.")
        print("-" * 72)
        if missing:
            dom = defaultdict(list)
            for s in missing:
                dom[reg[s].get("domain", "?")].append(s)
            for d, ss in sorted(dom.items()):
                print(f"  [{d}] {', '.join(ss)}")
        else:
            print("  none — the catalogue covers every required skill")

        print("\n" + "-" * 72)
        print(f"SUMMARY: {len(covered)} course(s) resolved, {len(missing)} skill(s) unprovided")
        print("-" * 72)

    return {"claimed": claimed, "unmatched": unmatched, "required": sorted(required),
            "order": order, "covered": covered, "missing": missing}


# Laksh's résumé surface, as free text exactly as it appears on the document.
DEMO = ["QLoRA", "4-bit NF4", "LoRA adapters", "Pre-LayerNorm", "RoPE",
        "Multi-Head Attention", "macro-F1", "ECE", "temperature scaling",
        "contrastive loss", "FAISS", "RAG", "C++", "PyTorch", "Kubernetes"]

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] != "--demo":
        terms = json.load(open(sys.argv[1], encoding="utf-8"))
    else:
        terms = DEMO
    resolve(terms)
