# GitHub Automation Setup Guide

This project uses several GitHub features and automation tools to maintain code quality and security.

## 🤖 Automated Features

### 1. Dependabot (`.github/dependabot.yml`)

**What it does:** Automatically creates PRs when dependency updates are available.

**Configuration:**

- Runs weekly on Mondays at 9 AM
- Groups minor and patch updates together
- Creates max 5 PRs at once
- Security updates are created immediately

**No setup required** - Works automatically once pushed to GitHub.

---

### 2. Pre-commit Hooks (`.pre-commit-config.yaml`)

**What it does:** Runs code quality checks before each commit.

**Setup (one-time):**

```powershell
# Install pre-commit
pip install pre-commit

# Install the git hooks
pre-commit install

# (Optional) Run on all files to test
pre-commit run --all-files
```

**What it checks:**

- ✅ Python syntax errors
- ✅ Trailing whitespace
- ✅ Code formatting (Black, isort)
- ✅ Security issues (detect-secrets)
- ✅ Large files
- ✅ Merge conflicts
- ✅ Debug statements

**Bypass (use sparingly):**

```powershell
git commit --no-verify -m "message"
```

---

### 3. GitHub Actions Workflows

#### **Python Code Quality** (`.github/workflows/python-check.yml`)

**Runs on:** Every push/PR to main or develop branches

**What it checks:**

- Python 3.9, 3.10, 3.11 compatibility
- Syntax validation
- Import tests for core modules
- Code style (Black, isort, Ruff)
- Hardcoded secrets
- Security vulnerabilities (Safety)

**No setup required** - Runs automatically in GitHub.

#### **Security Scan** (`.github/workflows/security-scan.yml`)

**Runs:** Weekly on Mondays + when requirements.txt changes

**What it does:**

- Scans for known vulnerabilities in dependencies
- Checks for dependency conflicts
- Creates GitHub issues if vulnerabilities found

**No setup required** - Runs automatically in GitHub.

---

## 📋 Issue & PR Templates

### Issue Templates (`.github/ISSUE_TEMPLATE/`)

- **Bug Report:** Structured bug reporting with environment details
- **Feature Request:** Standardized feature suggestions

**Usage:** When creating a new issue on GitHub, select the appropriate template.

### Pull Request Template (`.github/pull_request_template.md`)

**Usage:** Automatically appears when creating a PR. Fill out the checklist.

---

## 🔐 Security

### Secret Detection (`.secrets.baseline`)

The pre-commit hook uses `detect-secrets` to prevent committing credentials.

**Known exceptions:**

- `config_constants.py` contains database credentials (documented placeholder)

**If a secret is detected:**

1. Remove the secret from your code
2. Add it to environment variables or secure config
3. Update `.secrets.baseline` if it's a false positive:
   ```powershell
   detect-secrets scan --baseline .secrets.baseline
   ```

---

## 🚀 Quick Start

**For contributors:**

```powershell
# Clone the repo
git clone <repo-url>
cd qs.python.instagram-downloader

# Install dependencies
pip install -r requirements.txt

# Setup pre-commit hooks
pip install pre-commit
pre-commit install

# Make changes and commit
git add .
git commit -m "Your message"  # Pre-commit hooks run automatically
```

**For maintainers:**
All automation works automatically once pushed to GitHub. No additional configuration needed.

---

## 📊 Monitoring

### GitHub Actions Status

View workflow runs at: `https://github.com/<username>/<repo>/actions`

### Dependabot PRs

View and merge at: `https://github.com/<username>/<repo>/pulls`

### Security Alerts

View at: `https://github.com/<username>/<repo>/security/dependabot`

---

## 🛠️ Customization

### Modify pre-commit hooks:

Edit `.pre-commit-config.yaml` and run:

```powershell
pre-commit autoupdate  # Update to latest versions
```

### Modify workflows:

Edit files in `.github/workflows/` and push to GitHub.

### Modify Dependabot:

Edit `.github/dependabot.yml` and push to GitHub.

---

## 🐛 Troubleshooting

**Pre-commit is slow:**

```powershell
pre-commit run --all-files  # Run once to cache
```

**Pre-commit hook failed:**

- Read the error message
- Fix the issue (usually formatting or syntax)
- Run `git add .` again
- Commit again

**False positive in secret detection:**

```powershell
# Add to baseline
detect-secrets scan --baseline .secrets.baseline
git add .secrets.baseline
```

**GitHub Actions failing:**

- Check the Actions tab for detailed logs
- Test locally with the same commands from the workflow
- Ensure all dependencies in requirements.txt are valid

---

## 📚 Additional Resources

- [Pre-commit Documentation](https://pre-commit.com)
- [GitHub Actions Documentation](https://docs.github.com/actions)
- [Dependabot Documentation](https://docs.github.com/code-security/dependabot)
- [Black Code Formatter](https://black.readthedocs.io)
- [Ruff Linter](https://github.com/astral-sh/ruff)
