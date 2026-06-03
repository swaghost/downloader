# QUICK FIX: GitHub 403 Authentication Error

## ❌ The Problem

```
fatal: unable to access 'https://github.com/...': The requested URL returned error: 403
```

GitHub **no longer accepts passwords** for git operations. You need a **Personal Access Token** (PAT).

---

## ✅ Solution (Choose One)

### Option 1: Personal Access Token (Easiest)

**Step 1:** Create token at https://github.com/settings/tokens/new

- Token name: `Instagram Downloader`
- Expiration: `90 days` (or your choice)
- Scopes: Check `✓ repo` and `✓ workflow`
- Click "Generate token"
- **COPY THE TOKEN** (you won't see it again!)

**Step 2:** Enable credential storage (one-time setup)

```powershell
git config --global credential.helper store
```

**Step 3:** Push again (it will ask for credentials)

```powershell
git push -u origin main
```

When prompted:

- Username: `swaghost`
- Password: **[PASTE YOUR TOKEN]**

✅ Done! Token is saved, you won't need to enter it again.

---

### Option 2: SSH Keys (More Secure, One-Time Setup)

**Step 1:** Generate SSH key

```powershell
ssh-keygen -t ed25519 -C "your_email@example.com"
# Press Enter 3 times (default location, no passphrase)
```

**Step 2:** Copy public key

```powershell
Get-Content ~/.ssh/id_ed25519.pub | Set-Clipboard
# Or manually open: C:\Users\sasse\.ssh\id_ed25519.pub
```

**Step 3:** Add to GitHub

- Go to: https://github.com/settings/ssh/new
- Title: `Dev Machine`
- Key: Paste the copied key
- Click "Add SSH key"

**Step 4:** Change remote to SSH

```powershell
git remote set-url origin git@github.com:swaghost/downloader.git
```

**Step 5:** Push

```powershell
git push -u origin main
```

✅ Done! No password needed ever again.

---

## 🔍 Verify It Worked

After pushing successfully:

```powershell
# Check remote URL
git remote -v

# Verify push succeeded
git log --oneline -1
```

Then visit: https://github.com/swaghost/downloader

---

## 💡 Quick Reference

**If you used PAT (Option 1):**

- Your token is stored in: `~/.git-credentials`
- To update token: Delete that file and push again

**If you used SSH (Option 2):**

- Your keys are in: `~/.ssh/id_ed25519` (private) and `~/.ssh/id_ed25519.pub` (public)
- Never share the private key!

---

## 🆘 Still Having Issues?

**Token doesn't work:**

- Verify you checked `repo` scope when creating token
- Make sure you copied the entire token
- Try creating a new token

**SSH doesn't work:**

- Test connection: `ssh -T git@github.com`
- Should say: "Hi USERNAME! You've successfully authenticated"
- If not, check key was added to GitHub

**Other errors:**

- See full guide: `Documentation/GIT_SETUP_GUIDE.md`
- GitHub docs: https://docs.github.com/en/authentication
