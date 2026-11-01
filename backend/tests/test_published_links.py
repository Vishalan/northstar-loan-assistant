"""Links shared outside the repo must keep working: these paths and anchors are referenced from elsewhere.

If one of these fails, either restore the path or update every place the link was shared.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text()

SHARED_PATHS = [
    "README.md",                  # https://github.com/Vishalan/northstar-loan-assistant
    "ARCHITECTURE.md",            # .../blob/main/ARCHITECTURE.md
    "docs/performance.md",        # .../blob/main/docs/performance.md
    "docs/demo/index.html",       # https://vishalan.com/northstar-loan-assistant/demo/ (GitHub Pages from /docs)
    "docs/demo/northstar.mp4",
    "docs/arch/index.html",       # https://vishalan.com/northstar-loan-assistant/arch/
    "docs/.nojekyll",
]
ARCHITECTURE_PAGE = "https://vishalan.com/northstar-loan-assistant/arch/"
ARCHITECTURE_MIRROR = "https://claude.ai/artifact/H3BRFCgnS9ZAsyuzPyfknH"
DEMO_PAGE = "https://vishalan.com/northstar-loan-assistant/demo/"


def anchors(markdown: str) -> set[str]:
    def slug(heading: str) -> str:
        return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")
    return {slug(m) for m in re.findall(r"^#{1,6} (.+)$", markdown, re.M)}


def test_shared_paths_exist():
    missing = [p for p in SHARED_PATHS if not (ROOT / p).exists()]
    assert not missing, f"shared links would break: {missing}"


def test_readme_start_here_links_and_promises():
    assert "## Start here" in README
    assert ARCHITECTURE_PAGE in README and ARCHITECTURE_MIRROR in README and DEMO_PAGE in README
    for path in ("ARCHITECTURE.md", "docs/performance.md", "docs/demo/northstar.mp4"):
        assert f"]({path})" in README, path
    # "runs without any API keys" and "connect Claude or another provider, including self-hosted"
    assert {"run-it-no-keys-needed", "model-providers"} <= anchors(README)
    for provider in ("ANTHROPIC_API_KEY", "LLM_PROVIDER=bedrock", "LLM_PROVIDER=vertex", "LLM_PROVIDER=selfhosted"):
        assert provider in README, provider


def test_demo_page_plays_the_video_in_the_repo():
    page = (ROOT / "docs/demo/index.html").read_text()
    assert 'src="northstar.mp4"' in page and "github.com/Vishalan/northstar-loan-assistant" in page


def test_architecture_page_is_a_full_document():
    page = (ROOT / "docs/arch/index.html").read_text()
    assert page.startswith("<!doctype html>") and "<title>Northstar Architecture</title>" in page
    assert not re.search(r"blue ?machines|interview|assignment", page, re.I)


def test_internal_readme_anchors_resolve():
    known = anchors(README)
    used = set(re.findall(r"\]\(#([\w\-]+)\)", README))
    assert used <= known, f"README links to missing headings: {used - known}"
