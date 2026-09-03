from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
CANONICAL = "https://mralehsas.github.io/ALBAZ-ASTEROID-ARCHIVE/"
TITLE_AR = "أرشيف الكويكبات"
TITLE_EN = "ALBAZ Asteroid Archive"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    robots = ROOT / "robots.txt"
    sitemap = ROOT / "sitemap.xml"
    config = ROOT / "web-config.js"
    readme = ROOT / "README.md"

    require(robots.exists(), "robots.txt is missing")
    require(sitemap.exists(), "sitemap.xml is missing")
    require(config.exists(), "web-config.js is missing")
    require(readme.exists(), "README.md is missing")

    robots_text = robots.read_text(encoding="utf-8")
    sitemap_text = sitemap.read_text(encoding="utf-8")
    config_text = config.read_text(encoding="utf-8")
    readme_text = readme.read_text(encoding="utf-8")

    require("User-agent: *" in robots_text, "robots.txt must address all crawlers")
    require("Allow: /" in robots_text, "robots.txt must allow crawling")
    require(f"Sitemap: {CANONICAL}sitemap.xml" in robots_text, "robots.txt must advertise the canonical sitemap")

    require(CANONICAL in sitemap_text, "sitemap must contain the canonical GitHub Pages URL")
    require("<urlset" in sitemap_text and "</urlset>" in sitemap_text, "sitemap must be a valid URL set")

    require(CANONICAL in config_text, "web-config must expose the canonical URL")
    require(TITLE_AR in config_text and TITLE_EN in config_text, "web-config must expose the bilingual SEO title")
    require("description" in config_text.lower(), "web-config must expose an SEO description")
    require("application/ld+json" in config_text, "web-config must install Schema.org JSON-LD")
    require("rel', 'canonical'" in config_text or 'rel", "canonical"' in config_text or "rel = 'canonical'" in config_text,
            "web-config must install a canonical link")
    require("og:title" in config_text and "og:description" in config_text and "og:url" in config_text,
            "web-config must install Open Graph metadata")
    require("twitter:card" in config_text, "web-config must install Twitter card metadata")

    require(CANONICAL in readme_text, "README must prominently link to the canonical public application")
    require(TITLE_AR in readme_text and TITLE_EN in readme_text, "README must identify the project bilingually")
    require("NASA/JPL" in readme_text and "JPL Horizons" in readme_text, "README must identify the scientific data services")

    # Keep crawler-facing text descriptive rather than keyword-stuffed.
    description_match = re.search(r"seoDescription\s*=\s*['\"](.+?)['\"]", config_text)
    if description_match:
        description = description_match.group(1)
        require(70 <= len(description) <= 220, "SEO description should be concise and descriptive")

    print("SEO CONTRACT: PASS")


if __name__ == "__main__":
    main()
