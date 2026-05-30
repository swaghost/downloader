# Instagram Scanning Process - Mermaid Diagrams

This directory contains 6 separate Mermaid diagram files documenting the complete Instagram content scanning process.

## Diagram Files

1. **[SCANNING-01-main.mmd](SCANNING-01-main.mmd)**  
   Main scanning flow from user click to completion, including login, URL validation, and content type detection.

2. **[SCANNING-02-reel.mmd](SCANNING-02-reel.mmd)**  
   Reel scanning subprocess with CDP capture, meta tag extraction, segment validation, and audio handling.

3. **[SCANNING-03-post.mmd](SCANNING-03-post.mmd)**  
   Post scanning subprocess including carousel detection (JSON-LD, DOM scraping, CDP strategies) and single item processing.

4. **[SCANNING-04-url-validation.mmd](SCANNING-04-url-validation.mmd)**  
   URL validation subprocess with malformed query auto-correction and expiration checking.

5. **[SCANNING-05-caption-tags.mmd](SCANNING-05-caption-tags.mmd)**  
   Caption and hashtag extraction subprocess separating text from tags.

6. **[SCANNING-06-error-handling.mmd](SCANNING-06-error-handling.mmd)**  
   Error detection, classification, and retry logic for network, access, Instagram, and system errors.

## How to View

**Option 1: Mermaid Preview Extension**

- Right-click on any `.mmd` file
- Select "Preview Mermaid Diagram"

**Option 2: VS Code Command**

- Open any `.mmd` file
- Press `Ctrl+Shift+P`
- Type "Mermaid: Preview"

## Improvement Areas

### 🎯 High Priority

1. **Type Detection Reliability** - Multiple strategies, confidence scoring
2. **Carousel Item Detection** - JSON-LD, DOM, CDP strategies
3. **URL Validation** - Retry logic for expired URLs
4. **Segment Capture** - Gap filling, audio sync validation
5. **Error Attribution** - Better categorization

### 🔧 Medium Priority

6. **Quality Verification** - Resolution validation
7. **Login Handling** - Session persistence, 2FA
8. **Caption/Tag Extraction** - Multiple strategies

### 📊 Testing & Validation

9. **Test Case System** - Automated regression testing
10. **Validation Checkpoints** - At key process stages

## Legend

- 🟢 Success Path
- 🔴 Error Path
- 🟡 Warning/Fallback Path
- 🔧 Auto-Correction
- ⚠️ Needs Attention
- ✅ Completed Successfully
- ❌ Failed
