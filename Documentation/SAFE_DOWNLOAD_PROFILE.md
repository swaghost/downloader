# 🛡️ Safe Downloading Profile

**Optimized for public-content downloading, minimizing automated rate-limit triggers, and maintaining human-like request patterns.**

## 🕒 1. Delay Intervals (Human-Pattern Timing)

- **Base delay window:**
  - Randomized between 1.8–4.2 seconds per request.

- **Burst-break insertion:**
  - After every 7–12 downloads, insert a 12–25 second pause.

- **Session-length pacing:**
  - After 40–60 total requests, insert a 2–5 minute cooldown.

- **Jitter injection:**
  - Add ± 0.3–0.7 seconds of micro-variance to every delay.

## 🧩 2. Header Randomization (Avoiding Fingerprint Uniformity)

- Rotate User-Agents from a pool of 6–12 common mobile/desktop strings.

- Vary Accept-Language between realistic US-centric patterns:
  - `en-US,en;q=0.9`
  - `en-US,en;q=0.8`
  - `en-US,en;q=0.7`

- Randomize minor headers:
  - `DNT: 1` vs `DNT: 0`
  - `Sec-Fetch-Site` variations

- Avoid static header order — shuffle non-critical headers.

## 🎞️ 3. Quality-Based Rotation (Load-Shaping Strategy)

- **Primary download: 720p**
  - Lower bandwidth → lower scrutiny.

- **Occasional 1080p pulls:**
  - Every 5–9 items, allow one 1080p request.

- **Fallback logic:**
  - If CDN returns slow/unstable response, auto-switch to 480p for that item only.

- **Never request multiple qualities of the same item** — that looks bot-like.

## 🔁 4. Retry Logic (Graceful, Non-Aggressive)

- **Retry count:** Max 2 retries per item.

- **Backoff pattern:**
  - Retry 1: wait 3–6 seconds
  - Retry 2: wait 10–20 seconds

- **Abort conditions:**
  - 429, 403, or repeated timeouts → skip and log.

- **Never retry instantly** — that's a detection trigger.

## 🌐 5. CDN Signature Diversification

- Rotate CDN endpoints when available (Instagram uses multiple edge nodes).

- **Cache-bust parameters:**
  - Append harmless randomized query strings:
    ```
    ?v=<random 6–10 chars>
    ```

- Avoid reusing expired URLs — always refresh the media URL before download.

- Respect short URL lifetimes (IG CDN links often expire within minutes).

## 📉 6. Bandwidth Smoothing (Avoiding Traffic Spikes)

- **Throttle max throughput:**
  - Keep under 3–6 MB/s sustained.

- **Chunked downloads:**
  - Read in 256–512 KB chunks with micro-pauses.

- **Avoid parallel downloads > 2 threads**
  - Multi-threading is fine, but keep it human-plausible.

- Insert random micro-pauses during large file transfers.

## 👤 7. Session Behavior Modeling (Human-Like Patterns)

- **Session length:**
  - 10–20 minutes of activity, then a natural break.

- **Random "scroll pauses":**
  - Insert 5–15 second idle periods between batches.

- **Vary request order:**
  - Don't download items strictly chronologically.

- **Simulate human inconsistency:**
  - Occasionally skip an item and return later.

## ⏳ 8. URL Expiration Awareness

- Check timestamp signatures in CDN URLs (often UNIX-style).

- Refresh URLs if older than 2–4 minutes.

- Avoid pre-fetching too many URLs at once — they'll expire mid-session.

- Log expiration failures and re-queue with fresh metadata.

## 🧬 9. Device / Client Fingerprinting Avoidance

- **Rotate device profiles:**
  - iPhone 13, Pixel 7, Windows Chrome, Safari desktop.

- Vary viewport sizes if using headless browsing.

- **Disable deterministic headless fingerprints:**
  - Randomize WebGL vendor
  - Randomize canvas fingerprint noise

- Avoid identical TLS fingerprints across long sessions.

## 📦 10. Download Ordering Strategy (Human-Plausible Flow)

- **Mix content types:**
  - Reels → Stories → Posts → Highlights → Reels again.

- Avoid downloading 50 reels in a row — that's bot-like.

- Insert "profile view" delays between batches.

- Randomly skip items and return later.

## 📊 11. Logging & Telemetry (For Your Automation Framework)

- **Log every request with:**
  - Timestamp
  - URL
  - Response code
  - Download size
  - Retry count

- **Track anomaly spikes:**
  - 429s
  - Slow responses
  - CDN failures

- Auto-adjust delays based on error patterns.

## 🧹 12. Cleanup & Deduplication

- Hash every file (SHA-256 or xxHash).

- Skip duplicates automatically.

- **Store metadata in CSV:**
  - URL
  - Timestamp
  - Media type
  - Resolution
  - Hash

- Organize by date saved, not date posted.

## 🖥️ 13. GUI Wrapper Behavior (If You Add One)

- Expose delay sliders
- Show progress bars
- Show session health indicators
- Warn on high error rates
- Allow "safe mode" toggle for stricter pacing

---

## Implementation Status

- [ ] **Delay Intervals** - Human-pattern timing with randomization
- [ ] **Header Randomization** - User-Agent, Accept-Language rotation
- [ ] **Quality-Based Rotation** - Smart quality selection (720p primary)
- [ ] **Retry Logic** - Graceful backoff pattern
- [ ] **CDN Diversification** - Endpoint rotation, cache-busting
- [ ] **Bandwidth Smoothing** - Throttling, chunked downloads
- [ ] **Session Behavior** - Human-like patterns, scroll pauses
- [ ] **URL Expiration** - Timestamp checking, auto-refresh
- [ ] **Fingerprint Avoidance** - Device profile rotation
- [ ] **Download Ordering** - Mixed content types
- [ ] **Logging & Telemetry** - Comprehensive request tracking
- [ ] **Deduplication** - File hashing, metadata storage
- [ ] **GUI Controls** - Safe mode toggle, health indicators

---

## Current Implementation Gap Analysis

Based on existing codebase:

### Already Implemented

- ✅ Basic retry logic exists in downloader
- ✅ CDN URL capture via Chrome DevTools Protocol
- ✅ File metadata storage in SQLite database
- ✅ Basic error logging

### Needs Implementation

- ⚠️ Human-pattern delay intervals (currently minimal delays)
- ⚠️ Header randomization (static headers)
- ⚠️ Quality-based rotation (downloads all available)
- ⚠️ Bandwidth throttling (no limits)
- ⚠️ Session behavior modeling (continuous operation)
- ⚠️ Fingerprint avoidance (static browser profile)
- ⚠️ Download ordering strategy (sequential)
- ⚠️ URL expiration handling (basic expiration detection exists)
- ⚠️ File deduplication (basic filename checking)
- ⚠️ GUI safe mode controls

### Priority for Next Implementation Phase

1. **Delay system** - Most critical for rate-limit avoidance
2. **Session behavior** - Natural activity patterns
3. **Header randomization** - Reduce fingerprinting
4. **Bandwidth throttling** - Avoid traffic spike detection
5. **GUI controls** - User-facing safe mode toggle
