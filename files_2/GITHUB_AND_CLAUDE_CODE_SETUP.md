# GitHub & Claude Code Integration Guide
## LLM-Powered Protest Event Classification

This guide walks you through:
1. Setting up your GitHub repository
2. Installing Claude Code CLI
3. Using Claude Code for development
4. Setting up CI/CD pipeline
5. Collaborating with Claude AI

---

## PART 1: GITHUB REPOSITORY SETUP

### Step 1: Create Repository Structure

```bash
# Create project directory
mkdir protest_llm_classifier
cd protest_llm_classifier

# Initialize git
git init
git config user.name "Your Name"
git config user.email "your.email@example.com"

# Create directory structure
mkdir -p src/{models,utils,prompts}
mkdir -p data/{raw,processed,predictions}
mkdir -p notebooks
mkdir -p tests
mkdir -p configs
mkdir -p docs
mkdir -p .github/workflows

# Create essential files (see structure below)
touch README.md
touch .gitignore
touch setup.py
touch pyproject.toml
touch .env.example
```

### Step 2: Directory Structure

```
protest_llm_classifier/
├── .github/
│   └── workflows/
│       ├── tests.yml
│       ├── lint.yml
│       └── deploy.yml
├── src/
│   ├── __init__.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── llm_classifier.py
│   │   ├── batch_processor.py
│   │   └── ppi_estimator.py
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── codebook_manager.py
│   │   ├── prompt_builder.py
│   │   └── validators.py
│   ├── prompts/
│   │   ├── zero_shot.txt
│   │   ├── few_shot.txt
│   │   └── chain_of_thought.txt
│   └── main.py
├── notebooks/
│   ├── 01_development.ipynb
│   ├── 02_validation.ipynb
│   └── 03_analysis.ipynb
├── tests/
│   ├── __init__.py
│   ├── test_classifier.py
│   ├── test_codebook.py
│   └── test_ppi.py
├── data/
│   ├── raw/
│   ├── processed/
│   └── predictions/
├── configs/
│   └── protest_codebook.yaml
├── docs/
│   ├── API.md
│   ├── DEVELOPMENT.md
│   └── DEPLOYMENT.md
├── .gitignore
├── .env.example
├── requirements.txt
├── setup.py
├── pyproject.toml
└── README.md
```

### Step 3: Create .gitignore

```bash
cat > .gitignore << 'GITIGNORE'
# Environment
.env
.env.local
venv/
env/
ENV/

# IDE
.vscode/
.idea/
*.swp
*.swo
*~
.DS_Store

# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Testing
.pytest_cache/
.coverage
htmlcov/

# Data
data/raw/*
data/processed/*
data/predictions/*
!data/.gitkeep

# Logs
logs/
*.log

# API Keys
.apikeys
secrets/

# Notebooks
.ipynb_checkpoints/

# OS
*.DS_Store
Thumbs.db
GITIGNORE
```

### Step 4: Create .env.example

```bash
cat > .env.example << 'ENVFILE'
# LLM API Keys
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
HUGGINGFACE_API_KEY=hf_...

# Model Selection
MODEL_SELECTION=gpt-4o
# Options: gpt-4o, claude-3-5-sonnet, llama-3-1-70b, mistral-large

# Inference Settings
TEMPERATURE=0.1
MAX_TOKENS=1000
BATCH_SIZE=50

# Database (optional)
DATABASE_URL=sqlite:///protest_events.db

# Development
DEBUG=False
LOG_LEVEL=INFO
ENVFILE

echo "Copy .env.example to .env and fill in your keys"
```

---

## PART 2: CLAUDE CODE INSTALLATION & SETUP

### Option A: Install Claude Code CLI (Recommended)

```bash
# On macOS/Linux
curl -fsSL https://get.anthropic.com/claude-code | bash

# On Windows (PowerShell)
irm https://get.anthropic.com/claude-code | iex

# Verify installation
claude-code --version

# Authenticate with GitHub
claude-code auth login
```

### Option B: Use Claude Code in VS Code

```bash
# Install VS Code extension
# Search for "Claude Code" in VS Code Extensions marketplace

# Or install via command line
code --install-extension Anthropic.claude-code

# Configure GitHub connection
# 1. Open VS Code
# 2. Cmd/Ctrl + Shift + P
# 3. Search "Claude Code: Connect to GitHub"
# 4. Authorize with your GitHub account
```

### Option C: Direct Integration with GitHub

**Set up GitHub OAuth for Claude:**

1. Go to https://github.com/settings/developers
2. Click "New OAuth App"
3. Fill in details:
   - Application name: "Claude Code Protest Classifier"
   - Homepage URL: https://claude.ai
   - Authorization callback URL: https://claude.ai/auth/callback
4. Copy Client ID and Client Secret
5. Add to `.env`:
   ```
   GITHUB_CLIENT_ID=your_client_id
   GITHUB_CLIENT_SECRET=your_client_secret
   ```

---

## PART 3: INITIAL GITHUB SETUP

### Step 1: Create GitHub Repository

```bash
# Create repo on GitHub at github.com/your-username/protest-llm-classifier

# Add remote
git remote add origin https://github.com/YOUR_USERNAME/protest-llm-classifier.git

# Create initial commit
git add .
git commit -m "Initial commit: project structure and documentation"
git branch -M main
git push -u origin main
```

### Step 2: Configure Branch Protection

```bash
# In GitHub web interface:
# 1. Go to Settings → Branches
# 2. Add rule for "main" branch
# 3. Enable:
#    - Require pull request reviews (1 reviewer)
#    - Require status checks to pass
#    - Require branches to be up to date
```

### Step 3: Add Collaborators

```bash
# In GitHub web interface:
# 1. Go to Settings → Collaborators
# 2. Add Claude AI as collaborator (if using Claude in Teams)
# 3. Set permissions (maintain, write, or read)
```

---

## PART 4: CLAUDE CODE WORKFLOW

### Using Claude Code to Implement Components

```bash
# Start Claude Code development session
claude-code start --repo ./protest_llm_classifier

# Example: Have Claude implement a module
cd src/models
claude-code implement llm_classifier.py --description "Implement LLMClassifier class supporting multiple models"

# Claude will:
# 1. Read your codebook and requirements
# 2. Generate implementation
# 3. Create code in llm_classifier.py
# 4. Run tests
# 5. Commit to git (with your approval)
```

### Common Claude Code Commands

```bash
# Create new file with Claude
claude-code create src/models/new_module.py

# Analyze existing code
claude-code analyze src/models/llm_classifier.py

# Generate tests for a module
claude-code test src/models/llm_classifier.py --coverage

# Debug issues
claude-code debug --error "ModuleNotFoundError: No module named 'pydantic'"

# Refactor code
claude-code refactor src/ --target "improve_type_hints"

# Generate documentation
claude-code docs src/models/

# Run linting
claude-code lint src/

# Create GitHub issue from code
claude-code issue --file src/models/llm_classifier.py --line 42
```

---

## PART 5: GIT WORKFLOW WITH CLAUDE CODE

### Feature Branch Development

```bash
# Create feature branch
git checkout -b feat/implement-llm-classifier

# Have Claude implement feature
claude-code implement --feature "llm-classifier"

# Claude will:
# 1. Create/modify files
# 2. Write tests
# 3. Commit changes

# Create pull request
git push origin feat/implement-llm-classifier

# Create PR on GitHub:
# 1. Go to repo → Pull requests
# 2. Click "New pull request"
# 3. Select: main ← feat/implement-llm-classifier
# 4. Add description
# 5. Request review
```

### Commit Strategy

```bash
# Claude commits with conventional commit format
# Format: <type>(<scope>): <subject>

# Examples:
# feat(classifier): implement zero-shot classification
# fix(ppi): correct confidence interval calculation
# docs(readme): add installation instructions
# test(batch): add batch processor tests
# refactor(prompts): simplify prompt templates
# chore(deps): update pydantic to 2.6.0
```

---

## PART 6: CI/CD PIPELINE

### GitHub Actions Workflow: tests.yml

```bash
mkdir -p .github/workflows
cat > .github/workflows/tests.yml << 'WORKFLOW'
name: Tests

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.9', '3.10', '3.11']

    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Python ${{ matrix.python-version }}
      uses: actions/setup-python@v4
      with:
        python-version: ${{ matrix.python-version }}
    
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt
        pip install pytest pytest-cov pytest-xdist
    
    - name: Run tests
      run: |
        pytest tests/ -v --cov=src --cov-report=xml
    
    - name: Upload coverage
      uses: codecov/codecov-action@v3
      with:
        files: ./coverage.xml

    - name: Test with different models (GPU)
      if: runner.os == 'Linux'
      run: |
        pytest tests/test_classifier.py::test_all_models -v
WORKFLOW
```

### GitHub Actions Workflow: lint.yml

```bash
cat > .github/workflows/lint.yml << 'WORKFLOW'
name: Lint & Format

on: [push, pull_request]

jobs:
  lint:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.10'
    
    - name: Install dependencies
      run: |
        pip install black flake8 mypy isort
    
    - name: Run black
      run: black --check src/ tests/
    
    - name: Run flake8
      run: flake8 src/ tests/
    
    - name: Run mypy
      run: mypy src/
    
    - name: Run isort
      run: isort --check-only src/ tests/
WORKFLOW
```

---

## PART 7: STRUCTURED PROMPT FOR CLAUDE CODE

Create a prompt file that Claude Code can use:

```bash
cat > .claude/implementation-guide.md << 'PROMPT'
# Claude Code Implementation Guide

## Project: LLM-Powered Protest Event Classification

### Context
- Using Halterman & Keith (2025) methodology
- Classification of protest events from unstructured text
- Multiple LLM model support (GPT-4o, Claude, Llama, Mistral)
- Statistical inference with Prediction-Powered Inference

### Codebook Location
- Main: configs/protest_codebook.yaml
- Reference: docs/Comprehensive_Meta_Codebook_Protest_Analysis.docx

### Implementation Standards

#### Code Style
- Python 3.9+
- Type hints required (mypy strict mode)
- Docstrings: Google style
- Line length: 100 characters
- Tests: pytest with >80% coverage

#### Modules to Create

1. **src/models/llm_classifier.py**
   - LLMClassifier class
   - Support: GPT-4o, Claude, Llama, Mistral
   - Methods: classify_zero_shot, classify_few_shot, classify_with_cot

2. **src/utils/codebook_manager.py**
   - Load YAML codebooks
   - Validate predictions
   - Format for prompts

3. **src/models/batch_processor.py**
   - Process multiple events
   - Error handling
   - Progress tracking

4. **src/models/ppi_estimator.py**
   - Prediction-Powered Inference
   - Confidence intervals
   - Statistical tests

5. **src/utils/prompt_builder.py**
   - Zero-shot prompts
   - Few-shot prompts
   - Chain-of-thought prompts

6. **tests/test_*.py**
   - Unit tests for each module
   - Integration tests
   - Mock LLM responses

### Dependencies
- langchain, pydantic, pandas, scipy, statsmodels
- See requirements.txt for complete list

### Important: Schema Compliance
- All predictions must include:
  - event_type (str)
  - confidence_score (float 0-1)
  - reasoning (str)
  - key_indicators (list)

### Testing Strategy
- Unit tests for isolated functionality
- Integration tests with mock LLMs
- Don't make actual API calls in tests
- Use fixtures for common data

PROMPT
```

---

## PART 8: DEVELOPMENT WORKFLOW

### Day 1: Initial Setup

```bash
# 1. Initialize repo (done above)
# 2. Create project structure
# 3. Push to GitHub

git add .
git commit -m "docs: initial project structure and workflow"
git push origin main
```

### Day 2-3: Core Implementation with Claude Code

```bash
# Create feature branch
git checkout -b feat/core-implementation

# Let Claude Code implement core modules
claude-code implement src/models/llm_classifier.py
claude-code implement src/utils/codebook_manager.py
claude-code implement src/models/batch_processor.py
claude-code implement src/models/ppi_estimator.py

# Push changes
git add src/
git commit -m "feat: implement core LLM classification modules"
git push origin feat/core-implementation

# Create pull request and request review
```

### Day 4-5: Testing & Refinement

```bash
# Create tests branch
git checkout -b feat/add-tests

# Have Claude generate tests
claude-code test src/ --generate-tests

# Push tests
git add tests/
git commit -m "test: add comprehensive unit and integration tests"
git push origin feat/add-tests
```

### Day 6: Documentation

```bash
# Create docs branch
git checkout -b docs/add-documentation

# Generate docs
claude-code docs src/ --format markdown

# Add example notebooks
# Edit notebooks/01_development.ipynb manually

git add docs/ notebooks/
git commit -m "docs: add API documentation and examples"
git push origin docs/add-documentation
```

### Day 7: Integration & Deployment

```bash
# Merge all branches
git checkout main
git pull origin main

# Merge feature branches via GitHub (PR → Merge)

# Tag release
git tag v0.1.0
git push origin v0.1.0
```

---

## PART 9: CLAUDE CODE WORKFLOWS IN PRACTICE

### Example 1: Create New Feature

```bash
# 1. Create feature branch
git checkout -b feat/add-few-shot-examples

# 2. Describe to Claude
claude-code create-feature \
  --name "Few-Shot Learning Examples" \
  --description "Add ability to load and use few-shot examples for classification" \
  --related-files "src/utils/prompt_builder.py" \
  --tests-required

# 3. Claude Code:
#    - Generates code
#    - Writes tests
#    - Commits with conventional commits
#    - Creates GitHub issue with progress

# 4. Review and merge via GitHub PR
```

### Example 2: Debug Issue

```bash
# 1. Create issue branch
git checkout -b fix/confidence-score-bug

# 2. Report issue to Claude
claude-code debug \
  --error "confidence_score occasionally > 1.0" \
  --file "src/models/llm_classifier.py" \
  --line 145

# 3. Claude Code:
#    - Analyzes code
#    - Identifies root cause
#    - Generates fix with tests
#    - Commits as fix()

# 4. Merge via PR
```

### Example 3: Performance Optimization

```bash
# 1. Create optimization branch
git checkout -b perf/optimize-batch-processing

# 2. Ask Claude for optimization
claude-code optimize \
  --target "batch_processor" \
  --metric "throughput" \
  --goal "50% faster processing"

# 3. Claude Code:
#    - Analyzes current code
#    - Identifies bottlenecks
#    - Implements optimizations
#    - Benchmarks before/after
#    - Commits as perf()
```

---

## PART 10: COLLABORATION WITH CLAUDE CODE

### Using Claude Code for Code Review

```bash
# 1. Push feature branch
git push origin feat/my-feature

# 2. Ask Claude to review
claude-code review feat/my-feature \
  --check-types \
  --check-tests \
  --check-docs \
  --check-performance

# 3. Claude generates review comments
# 4. Address comments
# 5. Push fixes
# 6. Claude verifies resolution
```

### Using Claude Code for Documentation Generation

```bash
# Generate comprehensive docs
claude-code docs-generate \
  --source src/ \
  --output docs/API.md \
  --format markdown \
  --include-examples

# Generate README with setup instructions
claude-code readme-generate \
  --project "Protest LLM Classifier" \
  --include installation verification
```

---

## PART 11: ADVANCED WORKFLOWS

### Handling Large Implementations

```bash
# Break large features into smaller tasks
claude-code task-breakdown \
  --feature "implement-full-ppi" \
  --max-tasks 5

# Claude Code creates issues for each:
# [ ] Implement PPI core calculation
# [ ] Add confidence interval estimation
# [ ] Add correlation estimation
# [ ] Write comprehensive tests
# [ ] Generate documentation

# Work through tasks in branches:
git checkout -b task/ppi-core-calc
# ... work ...
git push origin task/ppi-core-calc
# Create PR
```

### Multi-Model Compatibility

```bash
# Have Claude ensure all models work
claude-code test-all-models \
  --models "gpt-4o,claude-3-5-sonnet,llama-3-1-70b" \
  --test-cases 50

# Claude creates test matrix
# Runs against each model
# Reports compatibility matrix
```

---

## PART 12: DEPLOYMENT & MONITORING

### Deploy to GitHub Pages (for documentation)

```bash
# Create deployment workflow
cat > .github/workflows/deploy-docs.yml << 'DEPLOY'
name: Deploy Docs

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    - uses: actions/setup-python@v4
      with:
        python-version: '3.10'
    - run: pip install mkdocs mkdocs-material
    - run: mkdocs build
    - uses: peaceiris/actions-gh-pages@v3
      with:
        github_token: ${{ secrets.GITHUB_TOKEN }}
        publish_dir: ./site
DEPLOY
```

### Monitor with Claude Code

```bash
# Monitor test coverage
claude-code monitor coverage \
  --threshold 80 \
  --alert-if-drops

# Monitor test speed
claude-code monitor tests \
  --alert-if-slow

# Generate weekly report
claude-code report --weekly
```

---

## QUICK REFERENCE: CLAUDE CODE COMMANDS

```bash
# Project setup
claude-code init
claude-code auth login
claude-code link-repo <repo-url>

# Development
claude-code create <file>
claude-code implement <feature>
claude-code refactor <file>
claude-code analyze <file>

# Testing
claude-code test <directory>
claude-code test-all-models
claude-code coverage

# Quality
claude-code lint
claude-code format
claude-code type-check
claude-code security-scan

# Documentation
claude-code docs
claude-code readme-generate
claude-code changelog-generate

# Debugging
claude-code debug
claude-code trace <error>

# Collaboration
claude-code review <branch>
claude-code suggest-improvements

# CI/CD
claude-code workflow-setup
claude-code deploy

# Reporting
claude-code report --daily
claude-code report --weekly
```

---

## TROUBLESHOOTING

### Claude Code won't authenticate

```bash
# Clear cached credentials
rm ~/.claude/credentials.json

# Re-authenticate
claude-code auth login --force

# Verify connection
claude-code auth check
```

### GitHub push fails

```bash
# Verify SSH key
ssh -T git@github.com

# Or use HTTPS with token
git remote set-url origin https://<token>@github.com/user/repo.git
```

### Tests fail in GitHub Actions

```bash
# Check logs
# 1. Go to repo → Actions
# 2. Click failed workflow
# 3. Expand failed step

# Debug locally with same Python version
python3.10 -m pytest tests/
```

---

## NEXT STEPS

1. ✅ Set up GitHub repository (this guide)
2. ✅ Install Claude Code CLI
3. ✅ Connect GitHub to Claude
4. Start development with `claude-code start`
5. Use Claude Code for implementation
6. Collaborate and iterate
7. Deploy and monitor

**Start here**: `git init && claude-code init`

