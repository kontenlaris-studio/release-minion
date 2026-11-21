#!/usr/bin/env python3
"""Render ReleaseMinion demo video: narrated slides from the recorded run.
Stdlib + PIL + ffmpeg + /opt/hatch/bin/tts (same pipeline as ContextCon)."""
import os, subprocess, sys
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "video")
os.makedirs(OUT, exist_ok=True)
FB = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FM = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

SECTIONS = [
    ("ReleaseMinion", "A release-readiness agent on the OpenMinion 0.1 SDK — Cortensor Hackathon #5",
     ["The question before every release:",
      "  is this project ready to ship — and if not,",
      "  what exactly blocks it?",
      "",
      "ReleaseMinion inspects a local Git repository",
      "with read-only tools and answers with evidence."],
     "Every release ends with the same manual checklist. Is the version bumped? Is the changelog written? What changed since the last tag? ReleaseMinion is a small agent built on the OpenMinion zero point one SDK that inspects a local Git repository with read-only tools, and answers that question with evidence."),
    ("How it works", "Tools, a two-phase flow, and deterministic guardrails",
     ["4 read-only tools: git_history, diff_summary,",
      "  project_version, changelog_status",
      "Phase A: agent inspects with tools, reasons in prose",
      "Phase B: structure-only turn -> Pydantic ReleaseReport",
      "Guardrails: every load-bearing field re-verified",
      "  against the raw tool outputs, corrections logged"],
     "The agent has four read-only tools: git history, diff summary, project version, and changelog status. It works in two phases: first it inspects and reasons in prose, then a structure-only turn produces a Pydantic-validated report. And because a small local model is an unreliable narrator, deterministic guardrails re-verify every load-bearing field against the raw tool outputs, and log every correction."),
    ("Local-first setup", "Ollama qwen2.5:1.5b — no API key, no hosted service",
     ["$ openminion config init --provider ollama",
      "$ openminion doctor --check-turn   -> turn smoke OK",
      "$ python selftest.py               -> 10 passed, 0 failed",
      "Project-scoped config ships in the repo:",
      "  config/agents.json + OPENMINION_HOME"],
     "Everything runs locally. The model is Qwen two point five, one point five billion parameters, served by Ollama. No API key, no hosted service. OpenMinion's doctor command verified a real turn before we ran anything, and the tool selftest passes ten out of ten without a model at all."),
    ("The demo repository", "A planted blocker, known ground truth",
     ["tag:        v0.2.0",
      "version:    0.3.0  (bumped in pyproject.toml)",
      "commits:    4 since the tag (feat, fix, docs, chore)",
      "changelog:  documents 0.2.0 only — 0.3.0 is missing",
      "",
      "Correct verdict: needs_work, blocked by the changelog"],
     "The demo repository has a planted blocker. The version was bumped to zero point three point zero, four commits landed since tag v zero point two point zero, but the changelog still only documents the old version. The correct verdict is: needs work, blocked by the missing changelog entry."),
    ("The recorded run", "evidence/run-log.txt — the model proposes, the facts decide",
     ["Model's draft verdict:  \"Ready for release\"",
      "[guardrail] readiness -> 'needs_work'",
      "Final report:  version 0.3.0 · tag v0.2.0 · 4 commits",
      "Blocker: CHANGELOG.md does not document 0.3.0",
      "Outputs: report.json + draft release-notes.md"],
     "In the recorded run, the model first proposed the wrong verdict: ready for release. The guardrail caught it, corrected the readiness to needs work, and the final report matches the ground truth on every field: version, tag, commit count, and the exact blocker. The run also writes a draft release-notes file."),
    ("Session memory", "Same session, follow-up answered from context",
     ["Q: Restate your report's version, tag,",
      "    readiness, and blockers.",
      "A: \"Version: 0.3.0. Last tag: v0.2.0.",
      "    Readiness: Needs work. Blockers:",
      "    CHANGELOG.md does not document 0.3.0...\"",
      "Recap-assisted recall: reliable on a 1.5B model"],
     "In the same session, a follow-up question is answered from context: version, tag, readiness, and blockers, all correct. One pattern mattered here: restating the verified report inside the question, what we call recap-assisted recall, makes session memory reliable even on a one point five billion parameter model."),
    ("What we learned", "Full notes in BUILDING_BLOCKS.md and WHAT_WE_LEARNED.md",
     ["1. Three timeout layers (60s / 90s / 300s) vs local CPU",
      "2. Proxy env vars break the localhost provider",
      "3. output_type + tools -> prose, not JSON (small models)",
      "4. Freshness classifier hijacks recall questions",
      "Repo: github.com/kontenlaris-studio/release-minion"],
     "Building this surfaced real findings for the OpenMinion team: three separate timeout layers that fight local C P U inference, proxy environment variables breaking the localhost provider, structured output returning prose when tools are present, and a freshness classifier that hijacks plain recall questions. All of it, with repro steps, is in the repository. ReleaseMinion: the model proposes, the facts decide."),
]

def slide(idx, title, subtitle, lines):
    img = Image.new("RGB", (1280, 720), (10, 25, 49))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 1280, 10], fill=(255, 122, 0))
    d.text((60, 48), title, font=ImageFont.truetype(FB, 40), fill=(255, 255, 255))
    d.text((60, 104), subtitle, font=ImageFont.truetype(FR, 21), fill=(255, 170, 80))
    y = 168
    for ln in lines:
        d.text((60, y), ln, font=ImageFont.truetype(FM, 23), fill=(220, 230, 245))
        y += 40
    d.text((60, 668), f"ReleaseMinion — Cortensor Hackathon #5 · {idx+1}/{len(SECTIONS)}",
           font=ImageFont.truetype(FR, 18), fill=(140, 160, 190))
    p = os.path.join(OUT, f"slide{idx}.png")
    img.save(p)
    return p

def dur(path):
    r = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    return float(r.stdout.strip())

def main():
    concat_v, concat_a = [], []
    for i, (title, sub, lines, narr) in enumerate(SECTIONS):
        png = slide(i, title, sub, lines)
        mp3 = os.path.join(OUT, f"narr{i}.mp3")
        if not os.path.exists(mp3):
            r = subprocess.run(["/opt/hatch/bin/tts", "speak", "--output", mp3,
                                "--text-stdin", "--voice", "avocado_v2:MAI_03",
                                "--language", "en"],
                               input=narr, capture_output=True, text=True)
            if r.returncode != 0:
                print("TTS FAIL", i, r.stderr[-300:]); sys.exit(1)
        d = dur(mp3) + 0.4
        concat_v.append(f"file '{png}'\nduration {d:.2f}")
        concat_a.append(f"file '{mp3}'")
        print(f"section {i}: {d:.1f}s")
    last = os.path.join(OUT, f"slide{len(SECTIONS)-1}.png")
    concat_v.append(f"file '{last}'")
    open(os.path.join(OUT, "vlist.txt"), "w").write("\n".join(concat_v) + "\n")
    open(os.path.join(OUT, "alist.txt"), "w").write("\n".join(concat_a) + "\n")
    out = os.path.join(OUT, "releaseminion-demo.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", os.path.join(OUT, "vlist.txt"),
                    "-f", "concat", "-safe", "0", "-i", os.path.join(OUT, "alist.txt"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", out], check=True)
    print("VIDEO OK", out, f"{dur(out):.1f}s")

if __name__ == "__main__":
    main()
