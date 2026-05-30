# Session Import Guide - Visual Walkthrough

## What You'll See in the GUI

When you open the application, the **Accounts** tab now has a new blue button:

```
┌─────────────────────────────────────────┐
│        Login to Instagram               │
├─────────────────────────────────────────┤
│ Username: [________________]            │
│ Password: [________________]            │
│                                         │
│        [    Login    ]                  │
│                                         │
│           ─── Or ───                    │
│                                         │
│  📁 Import Session from Browser Cookies │  ← NEW BUTTON!
└─────────────────────────────────────────┘
```

## Step-by-Step Process

### Step 1: Click the Import Button

Click the blue **"📁 Import Session from Browser Cookies"** button.

### Step 2: Read the Instructions

A popup appears with instructions:

```
╔═══════════════════════════════════════════════╗
║  Import Session from Browser                  ║
╠═══════════════════════════════════════════════╣
║  This feature imports Instagram cookies       ║
║  from your browser.                           ║
║                                               ║
║  How to export cookies:                       ║
║                                               ║
║  1. Install Cookie Editor extension           ║
║     (Chrome/Firefox)                          ║
║  2. Login to Instagram in your browser        ║
║  3. Click Cookie Editor → Export →            ║
║     Export as JSON                            ║
║  4. Save the JSON file                        ║
║  5. Select that file in the next dialog       ║
║                                               ║
║  See TROUBLESHOOTING.md for detailed          ║
║  instructions.                                ║
╠═══════════════════════════════════════════════╣
║          [  OK  ]  [ Cancel ]                 ║
╚═══════════════════════════════════════════════╝
```

Click **OK** to continue.

### Step 3: Select Your JSON File

A file picker opens. Navigate to where you saved your exported cookies JSON file and select it.

```
┌─────────────────────────────────────────────┐
│  Select Instagram Cookies JSON File         │
├─────────────────────────────────────────────┤
│  📁 Documents                                │
│    📄 instagram_cookies.json  ← Select this │
│    📄 other_file.txt                         │
│  📁 Downloads                                │
├─────────────────────────────────────────────┤
│  File name: instagram_cookies.json          │
│  File type: JSON Files (*.json)             │
│                                             │
│            [ Open ]  [ Cancel ]             │
└─────────────────────────────────────────────┘
```

### Step 4: Enter Your Username

A prompt appears asking for your Instagram username:

```
┌─────────────────────────────────────┐
│     Enter Username                   │
├─────────────────────────────────────┤
│  Enter your Instagram username:     │
│                                     │
│  [your_instagram_username______]   │
│                                     │
│         [  OK  ]  [ Cancel ]        │
└─────────────────────────────────────┘
```

Type your Instagram username (without @) and click **OK**.

### Step 5: Success!

If everything works, you'll see:

```
╔═══════════════════════════════════════════════╗
║                  Success                      ║
╠═══════════════════════════════════════════════╣
║  Session imported successfully!               ║
║                                               ║
║  Logged in as your_username                   ║
║  Session saved to: your_username.session      ║
╠═══════════════════════════════════════════════╣
║                  [  OK  ]                     ║
╚═══════════════════════════════════════════════╝
```

The status at the bottom of the Accounts tab updates:

```
✓ Logged in as your_username
```

### Step 6: Use the App!

Now you can:

- Go to **Browse** tab
- Click **Load Saved Posts**
- Select posts to download
- Download them!

## Exporting Cookies from Browser

### Chrome/Edge:

1. **Install Cookie Editor:**
   - Go to: https://chrome.google.com/webstore/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm
   - Click "Add to Chrome"

2. **Export cookies:**
   - Go to https://instagram.com (make sure you're logged in)
   - Click the Cookie Editor extension icon (usually top-right)
   - Click "Export" at the bottom
   - Click "Export as JSON"
   - Save the file (e.g., `instagram_cookies.json`)

### Firefox:

1. **Install Cookie Editor:**
   - Go to: https://addons.mozilla.org/en-US/firefox/addon/cookie-editor/
   - Click "Add to Firefox"

2. **Export cookies:**
   - Go to https://instagram.com (make sure you're logged in)
   - Click the Cookie Editor extension icon
   - Click "Export"
   - Click "Export as JSON"
   - Save the file (e.g., `instagram_cookies.json`)

## What the JSON File Looks Like

The exported JSON should contain cookies including the `sessionid`:

```json
[
  {
    "domain": ".instagram.com",
    "name": "sessionid",
    "value": "1234567890%3Aabcdefghijk...",  ← This is what we need
    ...
  },
  {
    "name": "csrftoken",
    "value": "xyz123...",
    ...
  },
  ...
]
```

The app automatically extracts the `sessionid` value and creates the session file.

## Troubleshooting

### "Could not find 'sessionid' cookie"

**Problem:** The JSON doesn't contain the sessionid.

**Solution:**

- Make sure you exported cookies from instagram.com, not another site
- Make sure you're logged into Instagram in the browser
- Try refreshing Instagram page before exporting

### "Session file created but login test failed"

**Problem:** The cookies are expired or invalid.

**Solution:**

- Logout and login again on Instagram in your browser
- Export fresh cookies
- Try again immediately (cookies can expire quickly)

### "Invalid JSON file"

**Problem:** The file isn't proper JSON format.

**Solution:**

- Make sure you used "Export as JSON" (not "Export as Netscape")
- Don't edit the file manually
- Try exporting again

## Why This Method Works

Instagram blocks automated login attempts, but:

- ✅ You logged in through a real browser (Instagram can't block that)
- ✅ We're just copying your existing session (not creating a new one)
- ✅ Instagram sees it as the same session from your browser
- ✅ No automation detection triggers

**This is the most reliable method to get logged in!**

## Session Lifespan

- Sessions typically last **90 days**
- You can use the app during this time without re-importing
- When it expires, just repeat the process
- No need to logout/login constantly

## Privacy & Security

**Is this safe?**

- ✅ The session file stays on your local machine
- ✅ No data is sent anywhere
- ✅ The app uses it exactly like your browser would
- ✅ You can delete the session file anytime

**Keep your session files secure** - they provide access to your Instagram account!
