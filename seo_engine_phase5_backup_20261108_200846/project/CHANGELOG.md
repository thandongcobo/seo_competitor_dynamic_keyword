# Changelog

## 0.4.1 - Playwright SERP collection fix
- Added the missing `scripts.collect_playwright_serp` module.
- Added persistent browser profile and browser geolocation to local SERP collection.
- Added Google/Bing result parsing with organic ranking positions generated locally.
- Added anti-automation challenge detection.
- Updated normalization and resolver to prefer Playwright SERP JSON.
- Updated the end-to-end pipeline so DataForSEO SERP is no longer called.
- Updated dashboard to read Playwright SERP snapshots.
- Kept DataForSEO Labs and Backlinks as the paid intelligence layer.
