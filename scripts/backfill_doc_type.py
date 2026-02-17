#!/usr/bin/env python3
"""Backfill doc_type metadata for existing papers.

Uses a manually curated mapping (no AI calls) for accuracy.

Usage:
    python scripts/backfill_doc_type.py          # dry-run (show classifications)
    python scripts/backfill_doc_type.py --apply   # actually update paper_meta.json
"""
import sys
import os
import json
import argparse

VALID_DOC_TYPES = {"paper", "report", "blog", "news", "essay", "other"}

# Manually curated: folder_name → doc_type
DOC_TYPE_MAP = {
    # ── OUTPUTS (32) ──────────────────────────────────────────────
    "65 lines of Markdown - a Claude Code sensation": "essay",
    "Access public data insights faster Data Commons MCP is now hosted on Google": "blog",
    "Agentic AI Frameworks Architectures, Protocols, and Design Challenges": "paper",
    "Agentic Systems A Guide to Transforming Industries with Vertical AI Agents": "paper",
    "Announcing the Agent2Agent Protocol (A2A)": "blog",
    "Apple picks Google\u2019s Gemini to run AI-powered Siri coming this year": "news",
    "Artificial Intelligence Index Report 2025": "report",
    "Building Autonomous AI Agents based AI Infrastructure": "paper",
    "CHATDB AUGMENTING LLMs WITH DATABASES AS THEIR SYMBOLIC MEMORY": "paper",
    "Conductor Update Introducing Automated Reviews": "blog",
    "FEATUREBENCH BENCHMARKING AGENTIC CODING FOR COMPLEX FEATURE DEVELOPMENT": "paper",
    "Flapping Airplanes on the future of AI \u2018We want to try really radically": "news",
    "FORMALJUDGE A Neuro-Symbolic Paradigm for Agentic Oversight": "paper",
    "GPT-4 Technical Report": "paper",
    "How Ricursive Intelligence raised $335M at a $4B valuation in 4 months": "news",
    "Infrastructure for AI Agents": "paper",
    "Learning to Compose for Cross-domain Agentic Workflow Generation": "paper",
    "LiteRT The Universal Framework for On-Device AI": "blog",
    "LLM Maybe LongLM SelfExtend LLM Context Window Without Tuning": "paper",
    "LLM Multi-Agent Systems Challenges and Open Problems": "paper",
    "OSWorld-Human Benchmarking the Efficiency of Computer-Use Agents": "paper",
    "REACT SYNERGIZING REASONING AND ACTING IN LANGUAGE MODELS": "paper",
    "Real-time rendering Why I stopped speaking in cache mode": "essay",
    "Reflexion Language Agents with Verbal Reinforcement Learning": "paper",
    "Search-o1 Agentic Search-Enhanced Large Reasoning Models": "paper",
    "SkillsBench Benchmarking How Well Agent Skills Work Across Diverse Tasks": "paper",
    "The AI Agent Index": "report",
    "The Landscape of Prompt Injection Threats in LLM Agents From Taxonomy to": "paper",
    "The Nightly Build Why you should ship while your human sleeps": "essay",
    "The supply chain attack nobody is talking about skill.md is an unsigned binary": "essay",
    "Two diff erent tricks for fast LLM inference": "blog",
    "Why Do Multi-Agent LLM Systems Fail": "paper",
    # ── ARCHIVES (16) ─────────────────────────────────────────────
    "20 The Trust Stack How Autonomous Agents Prove They Did What They Claim": "essay",
    "[UMBRA-734] AI consciousness": "essay",
    "A Survey on LLM-based Multi-Agent System Recent Advances and New Frontiers in": "paper",
    "After all the hype, some AI experts don\u2019t think OpenClaw is all that exciting": "news",
    "An AI Agent Published a Hit Piece on Me": "essay",
    "Beyond the Chatbot A Blueprint for Trustable AI": "blog",
    "BuildingaTUI iseasynow": "blog",
    "Claude Code Is Being Dumbed Down": "essay",
    "Easy FunctionGemma finetuning with Tunix on Google TPUs": "blog",
    "GLM-5 From Vibe Coding to Agentic Engineering": "blog",
    "Memory OS of AI Agent": "paper",
    "microgpt": "blog",
    "OpenClaw founder Peter Steinberger is joining OpenAI OpenClaw will live on as": "news",
    "OpenClaw, OpenAI and the future": "essay",
    "PHILOSOPHY OF AWARENESS 77.3 (LLM VERSION) THERMODYNAMICS OF MEANING THE": "essay",
    "Steve Yegge on AI Agents and the Future of Software Engineering": "essay",
}


def main():
    parser = argparse.ArgumentParser(description="Backfill doc_type for existing papers")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default is dry-run)")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    updated = 0
    skipped = 0
    missing = 0
    unmapped = 0

    for search_dir_name in ("outputs", "archives"):
        search_dir = os.path.join(base_dir, search_dir_name)
        if not os.path.isdir(search_dir):
            continue
        for folder_name in sorted(os.listdir(search_dir)):
            folder_path = os.path.join(search_dir, folder_name)
            if not os.path.isdir(folder_path):
                continue
            meta_path = os.path.join(folder_path, "paper_meta.json")
            if not os.path.isfile(meta_path):
                missing += 1
                continue
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"  [ERROR ] {search_dir_name}/{folder_name} — {e}")
                continue

            if meta.get("doc_type"):
                skipped += 1
                continue

            doc_type = DOC_TYPE_MAP.get(folder_name)
            if not doc_type:
                unmapped += 1
                print(f"  [NOMAP ] {search_dir_name}/{folder_name}")
                continue

            print(f"  [{doc_type:6s}] {search_dir_name}/{folder_name}")
            updated += 1

            if args.apply:
                meta["doc_type"] = doc_type
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"\nDone: {updated} updated, {skipped} already set, {unmapped} unmapped, {missing} no meta.")
    if not args.apply and updated > 0:
        print("Run with --apply to save changes.")


if __name__ == "__main__":
    main()
