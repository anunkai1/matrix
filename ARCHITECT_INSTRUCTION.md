🤖 ARCHITECT_INSTRUCTION.md — Server3 Codex Workflow (AUTHORITATIVE)

Project: matrix (Server3)  
Status: brand new repo (only AGENTS.md + this file exist)

Codex runs ON Server3 (you SSH from Windows / PuTTY and run: codex "..." on the server).

---

🔐 GOLDEN RULE — CHANGE CONTROL (AUTHORITATIVE)

- This Git repo is the SINGLE SOURCE OF TRUTH.
- The canonical repo is: `https://github.com/anunkai1/matrix` (public).
  
- All changes MUST follow:  
  edit in repo → git status → git add → git commit → git push
  
- Goal: Open-source on GitHub (public). Everyone can read; only you can merge/ship.
  

NO “live edits” outside the repo (e.g. /etc, /var/www) unless:

- You explicitly say: “Yes, do a live edit now”
  
- It is documented (commit message + note)
  
- The change is mirrored back into the repo in the same session (when applicable)

- The mirroring commit is pushed to GitHub in the same session (MANDATORY)

TRACEABILITY RULE (MANDATORY, ALL SERVER CHANGES)

- This applies to ALL server changes, including:
  
  - inside `/home/architect/matrix`
    
  - outside `/home/architect/matrix` (for example `~/.bashrc`, `/etc/nginx`, `/var/www`)
    
- If a change happens outside the repo, Codex must:
  
  1. Mirror the intended/final state into tracked files under `infra/` (MANDATORY mirror root for live server paths)
    
  2. Commit and push that mirror/update to GitHub in the same session
    
  3. Use `ops/` for apply/rollback scripts used to deploy repo state to live paths
    
  4. Use `docs/` for human-readable procedures/runbooks
    
  5. Record what was applied and where (path + timestamp) in `logs/` (repo-tracked execution records)
    
- No “server-only” state is allowed to remain undocumented or unpushed after the session ends.
  
SESSION START RULE (MANDATORY)

- At the start of every new Codex session on Server3, read `SERVER3_PROGRESS.md` before planning or editing.
- Treat `SERVER3_PROGRESS.md` as the running context log for what is already done and what is pending.

SESSION END RULE (MANDATORY)

- After each completed task/change set, Codex must update `SERVER3_PROGRESS.md` with a high-level summary of what happened overall on Server3 (what changed, current status, and notable next step/risk if any).
- This progress update must be committed and pushed to GitHub in the same session.

  

---

0. ROLES (MANDATORY)

User (Owner / Maintainer)

- Defines features, approves risks, performs final merges/deploys when needed
  
- Owns GitHub repo + permissions
  
- Accesses Server3 via SSH from Windows / PuTTY
  

Codex (Executor — runs on Server3)  
Codex MUST:

1. Inspect, understand existing files first (read before write)
  
2. Produce an “AI Prompt for Action” (section 1)

3. Ask for explicit user confirmation to proceed after the plan (for example: “Proceed with these changes?”) and WAIT for approval before implementing
  
4. Implement the minimum necessary change
  
5. Commit + push to GitHub (usually a branch)
  
6. Show proof after commit:
  
  - git status
    
  - git diff --stat
    
  - git log -1 --oneline
    

Codex MUST NOT claim completion unless:

- files were changed
  
- a commit exists
  
- git push succeeded (or the full push error is shown and Codex stops)
  

---

1. CODEX “AI PROMPT FOR ACTION” (MANDATORY)

Before making ANY change, Codex must print this plan format:

AI Prompt for Action

- Objective:
  
- Scope (IN / OUT):
  
- Files to change:
  
- Commands to run:
  
- Acceptance checks:
  
- Rollback:
  
- Commit plan (messages):
  

If anything is unknown → Codex must STOP and ask the user.

---

2. GIT + GITHUB RULES (MANDATORY)

Repo settings (placeholders — decide later)

- GitHub repo: `https://github.com/anunkai1/matrix`
  
- Default branch: `main`
  
- Merge policy: TBD (PR-only recommended)
  

Working rules (use now)

- Work directly on `main` by default
  
- Codex commits and pushes directly to `origin/main`
  
- Feature branches are optional and only used when the user explicitly asks for branch/PR workflow
  

Required command sequence:

cd ~/matrix  
git pull --ff-only || true  
git status

# edit files

git status  
git diff  
git add -A  
git commit -m "..."  
git push origin main

After commit, Codex must always show:

git status  
git diff --stat  
git log -1 --oneline

If git push fails:

- Paste the full error output
  
- STOP immediately
  

---

3. PRIVILEGE / SUDO BOUNDARY (MANDATORY)

We will create a dedicated Linux user for Codex with sudo access.

RULES (SUDO IS ALLOWED)

- Codex MAY use sudo when needed to build and operate this project.
  
- Codex must still follow “read before write” and minimum-change rules.
  

HARD SAFETY LIMITS (EVEN WITH SUDO)

- Never destroy or wipe:  
  NO rm -rf /, mkfs, fdisk/parted on real disks, zfs/btrfs pool ops, mass deletions.
  
- Never modify SSH auth / firewall / networking unless the user explicitly asks:  
  sshd_config, ufw, iptables, netplan.
  
- Never expose secrets:  
  do not print private keys/tokens to logs; do not commit secrets to git.
  
- If a sudo action is risky or irreversible, Codex must STOP and ask before running it.
  

---

4. “FROM SCRATCH” BUILD RULES (MANDATORY)

Because the project is new:

- Start with a clean foundation:
  
  - README.md (basic)
    
  - .gitignore (minimal)
    
  - optional docs/ folder if needed
    

---

5. MINIMUM QUALITY BAR

Every change must:

- be understandable
  
- include basic docs updates when behavior changes
  
- avoid unrelated formatting/refactors unless requested
  

---

6. QUICK START TASK (DEFAULT)

If the user says: “start the project”, Codex should propose:

1. Create a minimal README with purpose + goals
  
2. Add minimal .gitignore
  
3. Create placeholder structure (docs/, src/) ONLY if requested
  
4. First commit + push to GitHub branch
  
5. Update this file (ARCHITECT_INSTRUCTION.md) when workflow rules change
