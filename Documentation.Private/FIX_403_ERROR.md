# FIXING: Permission denied to swaghost (403 Error)

## ❌ The Error

```
remote: Permission to swaghost/downloader.git denied to swaghost.
fatal: unable to access 'https://github.com/swaghost/downloader.git/': The requested URL returned error: 403
```

## 🎯 Root Causes (Check in Order)

### 1. Repository Doesn't Exist Yet (MOST COMMON)

**Check:** Open https://github.com/swaghost/downloader in browser

- If you get 404 → Repo doesn't exist
- If you see repo page → Repo exists

**Fix if missing:**

1. Go to: https://github.com/new
2. Repository name: `downloader`
3. **DO NOT** check: Add README, .gitignore, or license
4. Click "Create repository"

---

### 2. Invalid or Missing Personal Access Token

**Symptoms:** Wrong password, or used GitHub password instead of token

**Fix:**

1. **Create token:** https://github.com/settings/tokens/new
   - Note: `Instagram Downloader`
   - Expiration: `90 days`
   - Scopes: ☑ **repo** (all boxes) + ☑ **workflow**
   - Generate and **COPY THE TOKEN**

2. **Clear cached bad credentials:**

   ```powershell
   cmdkey /delete:"git:https://github.com"
   ```

3. **Configure credential manager:**

   ```powershell
   git config --global credential.helper manager-core
   ```

4. **Push with token:**
   ```powershell
   git push -u origin main
   ```

   - Username: `swaghost`
   - Password: **[PASTE YOUR TOKEN]**

---

### 3. Token Missing Required Scopes

**Symptoms:** Token exists but still getting 403

**Fix:**

- Delete old token: https://github.com/settings/tokens
- Create new token with **full `repo` scope** (all checkboxes)
- Clear cached credentials (see above)
- Try pushing again

---

## ✅ Complete Fix Checklist

Run these commands in order:

```powershell
# 1. Verify repo exists
start https://github.com/swaghost/downloader
# If 404 → Create repo at https://github.com/new

# 2. Clear bad credentials
cmdkey /delete:"git:https://github.com"

# 3. Configure credential manager
git config --global credential.helper manager-core

# 4. Create token (if you haven't)
start https://github.com/settings/tokens/new
# Copy the generated token

# 5. Push (will ask for credentials)
git push -u origin main
# Username: swaghost
# Password: [paste token]
```

---

## 🔍 Verify It Worked

After successful push:

```powershell
# Should show your commits on GitHub
start https://github.com/swaghost/downloader

# Should show "Your branch is up to date"
git status
```

---

## 🆘 Still Not Working?

### Option A: Switch to SSH (No tokens needed)

```powershell
# 1. Generate SSH key
ssh-keygen -t ed25519 -C "your_email@example.com"

# 2. Copy public key
Get-Content ~/.ssh/id_ed25519.pub | Set-Clipboard

# 3. Add to GitHub
start https://github.com/settings/ssh/new
# Paste the key and save

# 4. Change remote to SSH
git remote set-url origin git@github.com:swaghost/downloader.git

# 5. Push
git push -u origin main
```

### Option B: Use GitHub CLI

```powershell
# Install: winget install GitHub.cli

# Login and push in one command
gh auth login
gh repo create downloader --public --source=. --remote=origin --push
```

---

## 🔐 Security Notes

- **NEVER** commit your Personal Access Token to git
- Tokens are stored securely in Windows Credential Manager
- Revoke old tokens at: https://github.com/settings/tokens
- SSH keys are more secure than tokens for long-term use

---

## 📚 More Help

- Full setup guide: `Documentation/GIT_SETUP_GUIDE.md`
- GitHub token docs: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/creating-a-personal-access-token
- Git credential manager: https://github.com/GitCredentialManager/git-credential-manager
