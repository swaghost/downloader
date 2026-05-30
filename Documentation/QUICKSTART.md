# Quick Start Guide

## ⚠️ Known Issue: Instagram Blocks Automated Logins

**If you see:** `Login error: "fail" status, message "Unexpected null login result"`

**This is normal.** Instagram actively blocks automated login attempts.

**Solution: Use the session creator script**

```bash
python create_session.py
```

Enter your credentials, and it will create a session file the GUI can reuse. See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for details.

---

## Get Running in 5 Minutes

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

**Expected output:**

```
Successfully installed instaloader-4.10.x PyQt5-5.15.x Pillow-10.x.x requests-2.x.x
```

### 2. Test Installation

```bash
python -c "import instaloader; import PyQt5; print('✓ All dependencies installed')"
```

### 3. Launch GUI

```bash
python main.py
```

**You should see:**

- A window titled "Instagram Downloader"
- Three tabs: Accounts, Browse, Download
- Ready to use!

### 4. First Login

**⚠️ IMPORTANT: Instagram often blocks automated logins**

**METHOD 1: Direct Browser Extraction (EASIEST! ⭐)**

1. **Login to Instagram** in Chrome or Firefox browser
2. **Close the browser completely** (not just the window - fully exit)
3. **Go to Accounts tab** in the GUI
4. **Click the green "🌐 Extract from Browser"** button
5. **Enter your Instagram username** when prompted
6. **Done!** Your session is automatically extracted and saved

No manual export needed! The app directly reads cookies from your browser.

**METHOD 2: Import from JSON File (if browser extraction fails)**

1. Go to **Accounts** tab in the GUI
2. Click **"📁 Import from JSON File"** button
3. Follow the popup instructions:
   - Install [Cookie Editor](https://chrome.google.com/webstore/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm) extension
   - Login to Instagram in your browser
   - Click Cookie Editor → Export → Export as JSON
   - Save the JSON file
4. Select the JSON file when prompted
5. Enter your Instagram username
6. Done! You're logged in

**METHOD 3: Command-line session creator**

```bash
python create_session.py
```

This uses a more robust login method. Follow the prompts, then the GUI will use the saved session.

**Direct Login (often blocked by Instagram)**

1. Go to **Accounts** tab
2. Enter your Instagram username
3. Enter your Instagram password
4. Click **Login**
5. If you see "null login result" error, use one of the methods above

**If login fails:** See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for more options.

### 5. Browse Saved Posts

1. Go to **Browse** tab
2. Click **Load Saved Posts**
3. Wait while your saved posts load
4. Select posts you want to download
5. Click **Add to Download Queue**

### 6. Download

1. Go to **Download** tab
2. Choose download directory (or use default)
3. Click **Start Download**
4. Watch progress bar
5. Done! Check your downloads folder

## CLI Quick Test

**Download a single post:**

```bash
python main.py download YOUR_USERNAME YOUR_PASSWORD POST_SHORTCODE
```

**Example:**

```bash
python main.py download myuser mypass CdNmOtkIOM-
```

## Troubleshooting Quick Fixes

### Import Error

```bash
pip install --upgrade -r requirements.txt
```

### GUI Won't Open

```bash
python main.py -v  # Verbose mode to see errors
```

### Login Fails

- Check username/password
- Try logging into Instagram app first
- Wait 10 minutes if rate limited

### Posts Won't Load

- Check internet connection
- Re-login from Accounts tab
- Check logs at `~/.instagram-downloader/app.log`

## File Locations

**User data:**

- Windows: `C:\Users\YourName\.instagram-downloader\`
- Mac/Linux: `~/.instagram-downloader/`

**Downloads (default):**

- Windows: `C:\Users\YourName\Downloads\Instagram\`
- Mac/Linux: `~/Downloads/Instagram/`

**Logs:**

- `~/.instagram-downloader/app.log`

## What Gets Saved

When you login:

- ✓ Session saved to `.instagram-downloader/sessions/`
- ✓ Account info in `.instagram-downloader/accounts.db`
- ✓ You won't need to login again (unless session expires)

When you download:

- ✓ Images saved as `.jpg`
- ✓ Videos saved as `.mp4`
- ✓ Captions saved as `.txt` (if metadata enabled)
- ✓ Organized by post shortcode

## Next Steps

1. **Test with one account** - Make sure everything works
2. **Download a few posts** - Verify quality is good
3. **Add more accounts** - Switch between multiple Instagram accounts
4. **Customize** - Edit `config.py` for your preferences

## Support

**Logs are your friend:**

```bash
# Windows
type %USERPROFILE%\.instagram-downloader\app.log

# Mac/Linux
tail -f ~/.instagram-downloader/app.log
```

**Common issues:**

- Rate limiting: Wait 10-15 minutes
- Session expired: Re-login from GUI
- Post unavailable: Post was deleted or account is private

## Performance

**Typical speeds:**

- Login: 5-10 seconds
- Load saved posts: 2-5 seconds per 50 posts
- Download: Depends on your internet speed
- No rate limit issues (handled by instaloader)

## Architecture at a Glance

```
main.py → gui.py → instagram_manager.py → instaloader library
              ↓
         account_manager.py → SQLite database
```

**Simple. Clean. Works.**
