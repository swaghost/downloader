# MoviePy 2.x Migration Guide

## Overview

This project uses **MoviePy 2.x** (specifically version 2.1.2+). MoviePy 2.0 introduced significant API changes that are **not backward compatible** with MoviePy 1.x.

## Current Status: ✅ FULLY MIGRATED

All code in this repository has been updated to use MoviePy 2.x API exclusively.

## Key API Changes (1.x → 2.x)

### 1. Import Structure ⚠️ CRITICAL

```python
# MoviePy 1.x (OLD - DEPRECATED)
from moviepy.editor import VideoFileClip, ImageClip, AudioFileClip, CompositeVideoClip

# MoviePy 2.x (NEW - CURRENT)
from moviepy import VideoFileClip, ImageClip, AudioFileClip, CompositeVideoClip
```

**Our Implementation**: We try MoviePy 2.x imports first, with automatic fallback to 1.x structure for compatibility (see `beat_composer_manager.py` lines 52-68).

### 2. Method Naming: set*\* → with*\* ⚠️ CRITICAL

All mutation methods changed from `set_*` to `with_*` pattern:

| MoviePy 1.x           | MoviePy 2.x            | Status            |
| --------------------- | ---------------------- | ----------------- |
| `.set_start(time)`    | `.with_start(time)`    | ✅ Updated        |
| `.set_end(time)`      | `.with_end(time)`      | ✅ N/A (not used) |
| `.set_duration(time)` | `.with_duration(time)` | ✅ Updated        |
| `.set_position(pos)`  | `.with_position(pos)`  | ✅ N/A (not used) |
| `.set_audio(audio)`   | `.with_audio(audio)`   | ✅ Updated        |
| `.set_fps(fps)`       | `.with_fps(fps)`       | ✅ Updated        |
| `.set_opacity(val)`   | `.with_opacity(val)`   | ✅ N/A (not used) |

### 3. Transformation Methods: verb → verb+ed ⚠️ CRITICAL

Transformation methods now use past tense:

| MoviePy 1.x             | MoviePy 2.x                              | Status            |
| ----------------------- | ---------------------------------------- | ----------------- |
| `.resize(size)`         | `.resized(size)`                         | ✅ Updated        |
| `.crop(x1, y1, x2, y2)` | `.cropped(x1, y1, x2, y2)`               | ✅ N/A (not used) |
| `.rotate(angle)`        | `.rotated(angle)`                        | ✅ N/A (not used) |
| `.subclip(t1, t2)`      | `.subclipped(t1, t2)`                    | ✅ Updated        |
| `.fadein(duration)`     | `.with_effects([vfx.fadein(duration)])`  | ✅ N/A (not used) |
| `.fadeout(duration)`    | `.with_effects([vfx.fadeout(duration)])` | ✅ N/A (not used) |

### 4. Effects System Changes

```python
# MoviePy 1.x (OLD)
from moviepy.video.fx.all import fadein, fadeout
clip = clip.fadein(1).fadeout(1)

# MoviePy 2.x (NEW)
from moviepy import vfx
clip = clip.with_effects([vfx.fadein(1), vfx.fadeout(1)])
```

**Status**: Not currently used in this project.

### 5. Audio/Video Composition

These remain **mostly unchanged**, but always use the new method names:

```python
# Both 1.x and 2.x (with updated methods)
from moviepy import CompositeVideoClip, concatenate_videoclips

# Composition - method calls must use with_*
final = CompositeVideoClip([bg, clip1, clip2])
final = final.with_audio(audio).with_fps(30)

# Concatenation - unchanged
result = concatenate_videoclips([clip1, clip2, clip3])
```

## Files Updated

### beat_composer_manager.py

**All MoviePy code isolated to this file.**

- **Lines 52-68**: Import structure with 2.x/1.x fallback
- **Line 590**: `with_start()` for ImageClip
- **Line 591**: `with_duration()` for ImageClip
- **Line 592**: `resized()` for ImageClip
- **Line 597**: `subclipped()` for VideoFileClip
- **Line 598**: `with_start()` for VideoFileClip
- **Line 599**: `resized()` for VideoFileClip
- **Line 622**: `with_audio()` for final video
- **Line 623**: `with_fps()` for final video

### gui.py

No direct MoviePy imports - only checks availability via `check_dependencies_available()`.

## Testing Checklist

When making changes involving MoviePy, verify:

- [ ] Import from `moviepy` (not `moviepy.editor`)
- [ ] All mutation methods use `with_*` pattern
- [ ] All transformation methods use past tense (e.g., `resized`)
- [ ] Test with actual video/image composition
- [ ] Verify exports render correctly

## Common Errors & Solutions

### Error: `'ImageClip' object has no attribute 'set_start'`

**Cause**: Using MoviePy 1.x API with MoviePy 2.x installed  
**Fix**: Change `.set_start()` to `.with_start()`

### Error: `'ImageClip' object has no attribute 'resize'`

**Cause**: Using MoviePy 1.x API with MoviePy 2.x installed  
**Fix**: Change `.resize()` to `.resized()`

### Error: `'VideoFileClip' object has no attribute 'subclip'`

**Cause**: Using MoviePy 1.x API with MoviePy 2.x installed  
**Fix**: Change `.subclip()` to `.subclipped()`

### Error: `No module named 'moviepy.editor'`

**Cause**: Trying to import from old MoviePy 1.x structure  
**Fix**: Change `from moviepy.editor import X` to `from moviepy import X`

## Installation

MoviePy 2.x is installed via:

```powershell
.\install-beat-composer.ps1
```

Or manually:

```bash
pip install "moviepy>=2.0.0"
```

## Version Pinning

Current `requirements.txt`:

```
moviepy>=1.0.3
```

**Recommendation**: Update to explicitly require 2.x:

```
moviepy>=2.0.0
```

This prevents accidental downgrades to 1.x.

## Additional Resources

- [MoviePy 2.0 Migration Guide (Official)](https://github.com/Zulko/moviepy/blob/master/MIGRATION_GUIDE.md)
- [MoviePy 2.x Documentation](https://zulko.github.io/moviepy/)
- [MoviePy GitHub](https://github.com/Zulko/moviepy)

## Future-Proofing

When adding new MoviePy functionality:

1. **Always check the method name** - assume `with_*` for mutations, past tense for transformations
2. **Import from `moviepy`** directly, not `moviepy.editor`
3. **Test immediately** - don't batch multiple API calls without testing
4. **Consult this guide** before using any MoviePy method

## Maintenance Log

| Date       | Change                      | Notes                                                          |
| ---------- | --------------------------- | -------------------------------------------------------------- |
| 2026-08-12 | Initial migration completed | All methods updated to 2.x API                                 |
| 2026-08-12 | Fixed preview errors        | Updated `resize()` → `resized()`, `subclip()` → `subclipped()` |

---

**Last Updated**: 2026-08-12  
**MoviePy Version**: 2.1.2  
**Status**: ✅ All code migrated and tested
