## Content Validation System

### Overview

The Content Validation System ensures that Instagram scans capture the **exact content you expect** by performing comprehensive checks during the scanning process.

### Problem Solved

Without validation, the scanner might:

- ❌ Load a different Instagram post (URL redirect)
- ❌ Capture content from adjacent posts/feed
- ❌ Get the wrong media type (reel vs carousel)
- ❌ Extract media from ads instead of the target post
- ❌ Capture content from a different author

**With validation enabled**, the system verifies:

- ✅ Shortcode matches expected URL
- ✅ Content type matches (reel/carousel/image)
- ✅ Author matches (optional)
- ✅ Media URLs are valid Instagram CDN links
- ✅ Caption matches expected text (optional, fuzzy)

---

## Quick Start

### 1. Enable Validation

Edit `validation_config.py`:

```python
ENABLE_VALIDATION = True
STRICT_VALIDATION_MODE = False  # Set True to abort on failure
```

### 2. Configure Checks

Choose which validations to perform:

```python
VALIDATION_CHECKS = {
    'url_match': True,          # ✅ RECOMMENDED
    'content_type': True,        # ✅ RECOMMENDED
    'author': False,             # Optional (requires author in DB)
    'media_urls': True,          # ✅ RECOMMENDED
    'caption_match': False,      # Optional (lenient)
}
```

### 3. Run Scan

The validation runs automatically during scanning. After each scan, you'll see:

```
============================================================
CONTENT VALIDATION REPORT
============================================================
Total Checks: 5
✓ Passed:     5
❌ Failed:     0
⚠️  Warnings:   0
Overall:      ✅ ALL PASSED
============================================================
```

---

## Validation Checks Explained

### 1. URL Match (Shortcode Verification)

**What it does**: Extracts the shortcode from the expected URL and verifies it matches the loaded page.

**Example**:

- Expected URL: `https://www.instagram.com/reel/DWmP9EyAFl-/`
- Shortcode: `DWmP9EyAFl-`
- Validation: Checks that loaded page contains this shortcode

**Why it matters**: Prevents loading wrong posts due to redirects or URL errors.

**Recommendation**: ✅ **Always enable**

---

### 2. Content Type Verification

**What it does**: Verifies the content type matches expectations:

- `reel` - Single video content
- `carousel` - Multiple images/videos
- `image` - Single photo

**Example**:

- Expected: `reel`
- Actual: `carousel` ❌ FAIL
- Result: Validation fails - you expected a video but got an image carousel

**Type normalization**:

- `video` → `reel`
- `album` → `carousel`
- `photo` → `image`

**Why it matters**: Ensures you're getting the right media type (prevents downloading images when you expected a video).

**Recommendation**: ✅ **Always enable**

---

### 3. Author Verification

**What it does**: Verifies the content is from the expected Instagram username.

**Example**:

- Expected author: `@theorangecrumble`
- Actual author: `@differentuser` ❌ FAIL

**Requirements**:

- Author must be stored in database (currently not implemented)
- OR pass author parameter during scan

**Why it matters**: Prevents capturing content from wrong accounts.

**Recommendation**: ⚠️ **Enable if you track authors** (currently optional)

---

### 4. Media URLs Validation

**What it does**: Validates extracted media URLs:

- ✅ URLs are well-formed (start with `http`)
- ✅ URLs are from Instagram CDN (`cdninstagram.com` or `fbcdn.net`)
- ✅ At least one media URL was extracted
- ⚠️ Warns if non-CDN URLs detected

**Example**:

```
✓ Media URLs validated: 3 item(s)
  • https://scontent-lga3-2.cdninstagram.com/video.mp4
  • https://scontent-lga3-2.cdninstagram.com/img1.jpg
  • https://scontent-lga3-2.cdninstagram.com/img2.jpg
```

**Why it matters**: Ensures valid media was extracted and prevents saving broken/invalid URLs.

**Recommendation**: ✅ **Always enable**

---

### 5. Caption Match (Fuzzy)

**What it does**: Compares first 100 characters of expected vs actual caption.

**Example**:

- Expected: `"Trump's entire political identity was built on one lie..."`
- Actual: `"Trump's entire political identity was built on one lie... [more content]"`
- Result: ✅ PASS (fuzzy match)

**Fuzzy matching**: Allows for:

- Encoding differences
- Truncated vs full text
- Minor formatting changes

**Why it matters**: Helps verify you got the right post, but very lenient.

**Recommendation**: ⚠️ **Optional** (useful for debugging, not critical)

---

## Configuration Options

### Strict Mode

```python
STRICT_VALIDATION_MODE = False  # Warning only
STRICT_VALIDATION_MODE = True   # Abort scan on failure
```

**Non-strict (False)**:

- Validation failures logged as ⚠️ warnings
- Scan continues and saves content
- Use for: Lenient validation, testing

**Strict (True)**:

- Validation failures raise exceptions ❌
- Scan aborts, content NOT saved
- Use for: Production, critical content

---

### Validation Behavior

```python
VALIDATION_OPTIONS = {
    'abort_on_failure': True,              # Stop if validation fails (strict mode only)
    'print_validation_report': True,        # Show report after scan
    'save_validation_results': True,        # Store results in database
    'min_carousel_items': 2,               # Minimum items for carousel
    'caption_fuzzy_match_length': 100,     # Characters to compare
}
```

---

## Usage Examples

### Example 1: Recommended Settings (Most Users)

```python
# validation_config.py
ENABLE_VALIDATION = True
STRICT_VALIDATION_MODE = False  # Warn but don't abort

VALIDATION_CHECKS = {
    'url_match': True,      # Verify shortcode
    'content_type': True,   # Verify type (reel/carousel/image)
    'author': False,        # Skip (not stored in DB yet)
    'media_urls': True,     # Verify URLs are valid
    'caption_match': False, # Skip (optional)
}
```

**Result**: Basic validation without being too strict. Warns on issues but doesn't abort scans.

---

### Example 2: Strict Mode (Critical Content)

```python
# validation_config.py
ENABLE_VALIDATION = True
STRICT_VALIDATION_MODE = True  # Abort on failure

VALIDATION_CHECKS = {
    'url_match': True,
    'content_type': True,
    'author': True,         # Enable if you have author in DB
    'media_urls': True,
    'caption_match': True,  # Verify caption too
}
```

**Result**: Maximum validation. Scan aborts if any check fails.

---

### Example 3: Minimal Validation (Testing)

```python
# validation_config.py
ENABLE_VALIDATION = True
STRICT_VALIDATION_MODE = False

VALIDATION_CHECKS = {
    'url_match': True,      # Only verify shortcode
    'content_type': False,
    'author': False,
    'media_urls': False,
    'caption_match': False,
}
```

**Result**: Only checks if URL matches. Useful for debugging.

---

## Interpreting Validation Reports

### Successful Validation

```
============================================================
CONTENT VALIDATION REPORT
============================================================
Total Checks: 5
✓ Passed:     5
❌ Failed:     0
⚠️  Warnings:   0
Overall:      ✅ ALL PASSED
============================================================

Detailed Results:
  ✓ url_match       - Shortcode: DWmP9EyAFl-
  ✓ content_type    - Type: reel, Items: 1
  ✓ author          - Author: @theorangecrumble
  ✓ media_urls      - 1 valid URL(s)
  ✓ caption         - Caption matched (fuzzy)
============================================================
```

**Meaning**: Everything validated successfully. Content is definitely what you expected.

---

### Validation Failure

```
============================================================
CONTENT VALIDATION REPORT
============================================================
Total Checks: 5
✓ Passed:     3
❌ Failed:     2
⚠️  Warnings:   0
Overall:      ❌ VALIDATION FAILED
============================================================

Detailed Results:
  ❌ url_match       - Expected DWmP9EyAFl-, got ABC123XYZ
  ✓ content_type    - Type: reel, Items: 1
  ❌ author          - Expected @theorangecrumble, got @differentuser
  ✓ media_urls      - 1 valid URL(s)
  ✓ caption         - Skipped (no expected caption)
============================================================
```

**Meaning**:

- ❌ **URL shortcode mismatch**: Loaded the wrong Instagram post!
- ❌ **Author mismatch**: Content is from wrong account!
- ⚠️ **Action needed**: Don't trust this content. Re-scan or check the URL.

---

### Warnings

```
Detailed Results:
  ✓ url_match       - Shortcode: DWmP9EyAFl-
  ✓ content_type    - Type: carousel, Items: 1 ⚠️
  ✓ author          - Skipped (no expected author)
  ✓ media_urls      - 1 valid URL(s)
```

**Meaning**:

- ⚠️ **Carousel with 1 item**: Expected multiple items, only got 1
- Usually means Instagram didn't load all carousel items
- **Action**: Re-scan or wait longer for page load

---

## Troubleshooting

### Issue: Validation fails but content looks correct

**Symptoms**:

```
❌ url_match       - Expected DWmP9EyAFl-, got DWmP9EyAFl-
```

**Cause**: Shortcode extraction failed or URL format unexpected

**Solution**:

1. Check URL format: `https://www.instagram.com/reel/SHORTCODE/`
2. Verify shortcode in database matches actual Instagram URL
3. Check `debug/SHORTCODE_selenium_debug.html` for actual loaded page

---

### Issue: Author validation always fails

**Symptoms**:

```
❌ author          - Expected @user, got None
```

**Cause**: Author not extracted from page

**Solution**:

1. Disable author validation if not critical:
   ```python
   VALIDATION_CHECKS = {'author': False}
   ```
2. Or implement author extraction in downloader.py (TODO)

---

### Issue: Content type mismatch (reel vs carousel)

**Symptoms**:

```
❌ content_type    - Expected reel, got carousel
```

**Cause**: Database has wrong content type, or Instagram changed the post

**Solution**:

1. Update database content_type to match actual
2. Or verify Instagram didn't change the post type
3. Check `debug/SHORTCODE_selenium_debug.html` to see actual page

---

### Issue: Too many warnings

**Symptoms**:

```
⚠️  Warnings:   5
```

**Cause**: Non-critical issues (non-CDN URLs, missing optional data)

**Solution**:

- Warnings are informational, not failures
- Review warning details to see if action needed
- Adjust `STRICT_VALIDATION_MODE` if warnings should be errors

---

## Testing the Validation System

Run the comprehensive test suite:

```bash
python test_content_validation.py
```

Expected output:

```
======================================================================
TEST SUMMARY
======================================================================
Tests run: 27
✓ Passed:  27
❌ Failed:  0
❌ Errors:  0
======================================================================
```

---

## Integration with Existing Scan Process

The validation system integrates with downloader.py:

1. **After URL load**: Validates shortcode and content type
2. **After media extraction**: Validates media URLs
3. **After caption extraction**: Validates caption (if enabled)
4. **Before saving**: Final validation report

**No code changes needed** - validation runs automatically when enabled in config.

---

## Future Enhancements

Planned features:

- [ ] Author extraction from Instagram page
- [ ] Engagement metrics validation (like/comment counts)
- [ ] Post date verification
- [ ] Hashtag validation
- [ ] Location verification (for geotagged posts)
- [ ] Machine learning-based content similarity check

---

## FAQ

**Q: Should I enable strict mode?**

A: Start with `STRICT_VALIDATION_MODE = False` for testing. Enable strict mode only after you've verified your database has correct information.

---

**Q: Which checks are most important?**

A: At minimum, enable:

- `url_match` (shortcode verification)
- `content_type` (reel/carousel/image)
- `media_urls` (valid URLs)

---

**Q: What if validation fails but I want to save anyway?**

A: Set `STRICT_VALIDATION_MODE = False`. Validation failures will be logged as warnings, but content will still be saved.

---

**Q: How do I know if I got the right content?**

A: Check the validation report:

- ✅ ALL PASSED = Definitely correct
- ⚠️ Warnings = Probably correct, review warnings
- ❌ VALIDATION FAILED = Wrong content, don't use

---

## Summary

**Benefits of Content Validation**:

- ✅ Ensures you get the exact content you expect
- ✅ Prevents capturing wrong posts/media
- ✅ Catches URL redirects and feed content
- ✅ Verifies content type (reel vs carousel)
- ✅ Validates media URLs are from Instagram CDN
- ✅ Provides detailed reports for troubleshooting

**Recommended for**:

- Production use (must have reliable content)
- Automated scanning (batch processing)
- Critical content (legal, archival)

**Optional for**:

- Manual one-off scans (you can verify visually)
- Testing/development

---

## Getting Help

If validation consistently fails:

1. Check `debug/SHORTCODE_selenium_debug.html` to see what Instagram actually loaded
2. Verify database entry has correct URL and content type
3. Review validation report for specific failures
4. Check if Instagram post was deleted/changed
5. Try disabling strict mode temporarily

For issues or questions, see the main README.md or open an issue.
