# Git Setup Guide - Push to GitHub

## 🚀 Quick Start (Step-by-Step)

### Step 1: Initialize Git Repository

```powershell
# Initialize git in your project
git init

# Check what files will be committed
git status
```

### Step 2: Create Initial Commit

```powershell
# Stage all files (respects .gitignore)
git add .

# Create first commit
git commit -m "Initial commit: Instagram Downloader with PyQt5 GUI"
```

**What gets committed:**

- ✅ All Python source files
- ✅ Documentation
- ✅ `config_local.example.py` (template)
- ✅ GitHub automation files
- ✅ `.gitignore`
- ❌ `config_local.py` (your credentials - gitignored)
- ❌ `settings.json` (user settings - gitignored)
- ❌ `__pycache__`, `.venv`, etc.

### Step 3: Create GitHub Repository

**Option A: Via GitHub Website**

1. Go to https://github.com/new
2. Repository name: `instagram-downloader` (or your choice)
3. Description: "Instagram saved posts downloader with PyQt5 GUI and SQL Server backend"
4. **Choose:** Public or Private
5. **DO NOT** initialize with README, .gitignore, or license (we already have these)
6. Click "Create repository"

**Option B: Via GitHub CLI** (if installed)

```powershell
gh repo create instagram-downloader --public --source=. --remote=origin
```

### Step 4: Connect to GitHub

After creating the repo on GitHub, you'll see commands like:

```powershell
# Add GitHub as remote origin
git remote add origin https://github.com/YOUR_USERNAME/instagram-downloader.git

# Rename branch to main (if needed)
git branch -M main

# Push to GitHub
git push -u origin main
```

**Replace `YOUR_USERNAME` with your actual GitHub username!**

---

## 📝 Complete Command Sequence

```powershell
# 1. Initialize git
git init

# 2. Stage all files
git add .

# 3. Create initial commit
git commit -m "Initial commit: Instagram Downloader with PyQt5 GUI"

# 4. Create repo on GitHub (via website or CLI)
#    Then add remote:

# 5. Add remote origin (REPLACE YOUR_USERNAME)
git remote add origin https://github.com/YOUR_USERNAME/instagram-downloader.git

# 6. Rename branch to main
git branch -M main

# 7. Push to GitHub
git push -u origin main
```

---

## ✅ Verification Checklist

After pushing, verify on GitHub:

- [ ] Source code is visible
- [ ] README.md displays on homepage
- [ ] `config_local.py` is NOT visible (gitignored)
- [ ] `config_local.example.py` IS visible (safe template)
- [ ] GitHub Actions appear in Actions tab
- [ ] Dependabot is enabled (check Security tab)

---

## 🔒 Security Verification

**Critical: Verify no secrets were committed**

```powershell
# Check what's in your last commit
git log --stat -1

# Verify config_local.py is NOT staged
git status

# Check if sensitive files are ignored
git check-ignore config_local.py settings.json
# Should output: config_local.py and settings.json
```

**If you accidentally commit secrets:**

```powershell
# Remove from git but keep local file
git rm --cached config_local.py
git commit -m "Remove accidentally committed credentials"
git push
```

---

## 🌿 Recommended Branch Strategy

```powershell
# Create develop branch for active development
git checkout -b develop
git push -u origin develop

# Work on features in branches
git checkout -b feature/new-feature
# ... make changes ...
git commit -m "Add new feature"
git push -u origin feature/new-feature
# Create Pull Request on GitHub
```

---

## 🔄 Daily Git Workflow

```powershell
# Before starting work
git pull

# Make changes, then:
git add .
git commit -m "Descriptive message"
git push

# Pre-commit hooks will run automatically
```

---

## 🛠️ Useful Git Commands

```powershell
# View commit history
git log --oneline --graph --decorate --all

# Undo last commit (keep changes)
git reset --soft HEAD~1

# Discard local changes
git restore .

# Update from GitHub
git pull

# View remote URL
git remote -v

# Change remote URL (if needed)
git remote set-url origin NEW_URL
```

---

## 🐛 Troubleshooting

**"fatal: unable to access... 403 error"**

GitHub no longer accepts passwords for HTTPS authentication. You need a Personal Access Token (PAT):

1. **Create a token:** Go to https://github.com/settings/tokens/new
   - Token name: "Instagram Downloader"
   - Expiration: 90 days or your choice
   - Scopes: Check `repo` (full control) and `workflow`
   - Click "Generate token" and **COPY IT** (you won't see it again)

2. **Use token when pushing:**

   ```powershell
   git push -u origin main
   # Username: your_github_username
   # Password: [paste your token]
   ```

3. **Save credentials (optional):**
   ```powershell
   git config --global credential.helper store
   # Token saved after first successful push
   ```

**Alternative: Use SSH instead of HTTPS:**

```powershell
# 1. Generate SSH key
ssh-keygen -t ed25519 -C "your_email@example.com"

# 2. Add public key to GitHub
# Copy ~/.ssh/id_ed25519.pub to https://github.com/settings/ssh/new

# 3. Change remote to SSH
git remote set-url origin git@github.com:USERNAME/instagram-downloader.git

# 4. Push
git push -u origin main
```

**"Authentication failed"**

- Use Personal Access Token instead of password
- Create at: https://github.com/settings/tokens
- Use token as password when prompted

**"Repository not found"**

- Verify remote URL: `git remote -v`
- Check you created the repo on GitHub
- Verify repository name matches

**"Permission denied (publickey)"**

- Setup SSH keys: https://docs.github.com/en/authentication/connecting-to-github-with-ssh
- Or use HTTPS with token

**"Pre-commit hooks failing"**

- Run: `pre-commit run --all-files` to see errors
- Fix issues or temporarily bypass: `git commit --no-verify`

---

## 📚 Additional Resources

- [GitHub Docs](https://docs.github.com)
- [Git Cheat Sheet](https://education.github.com/git-cheat-sheet-education.pdf)
- [Pro Git Book](https://git-scm.com/book/en/v2)

---

## 🎯 Next Steps After First Push

1. **Enable GitHub Features:**
   - Go to Settings → Security → Enable Dependabot alerts
   - Go to Settings → Secrets → Add any secrets for GitHub Actions (if needed)

2. **Setup GitHub Pages (optional):**
   - Settings → Pages → Deploy from branch `main` → `/Documentation`

3. **Configure Branch Protection:**
   - Settings → Branches → Add rule for `main`
   - Require pull request reviews
   - Require status checks to pass

4. **Add Topics:**
   - Top of repo page → Add topics: `instagram`, `downloader`, `pyqt5`, `python`, `sqlserver`

5. **Write Good README:**
   - Add badges (build status, license, etc.)
   - Add screenshots of the GUI
   - Clear installation instructions
