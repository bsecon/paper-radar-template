# paper-radar: setup guide for Claude Code

This repository was created from the paper-radar template. If the person has opened you here
and asks to set up their radar, walk them through the steps below, one at a time, running the
commands for them where you can and asking only for what you cannot know. Check `README.md`
for how the radar works.

## Setup checklist

1. **Prerequisites.** Mac or Windows (Linux works too). On Windows, use Git Bash as the shell
   for every command below; the scripts are bash. Check which of these exist: `uv` (`uv --version`), the GitHub CLI
   (`gh --version`), and Claude Code (`claude --version`, or inside the Claude desktop app).
   Install what is missing. Mac: `curl -LsSf https://astral.sh/uv/install.sh | sh`, `gh` from
   https://cli.github.com, Claude Code with `curl -fsSL https://claude.ai/install.sh | bash`.
   Windows (PowerShell): `winget install Git.Git GitHub.cli astral-sh.uv`, then
   `irm https://claude.ai/install.ps1 | iex`; open a new Git Bash window afterwards.
   A Claude subscription (Pro or Max) is needed; no API key.
2. **GitHub login.** `gh auth login`, then `gh auth setup-git`. The repo this folder was cloned
   from is where digests and alerts will be posted as issues. Confirm with `gh repo view`.
3. **Claude login for the headless runs.** `bin/claude-login.sh` opens a browser, stores a
   long-lived token (macOS keychain, or `~/.config/paper-radar/token` elsewhere), and runs one
   test call.
4. **Dependencies and check.** `uv sync`, then `uv run radar doctor`: it must show the Claude
   binary, `gh`, and the GitHub repo.
   Windows, inside the Claude desktop app: the app redirects writes to `AppData\Roaming`, which
   breaks uv's Python download ("Missing expected target directory for Python minor version
   link"). Run `export UV_PYTHON_INSTALL_DIR="$HOME/.local/share/uv/python"` first, and add the
   same line to `~/.bashrc` so later runs agree. If `claude` is installed but not on PATH
   (`~/.local/bin/claude.exe`), the radar finds it there anyway; `radar doctor` confirms.
5. **Profile.** This is the step that matters. Ask for the person's CV, website, or two or three
   papers (PDFs or links), read them, and write `profile.md` following the headings already in
   it. Show the draft and revise until they are happy. Concrete beats general.
6. **Sources.** In `config/sources.yml`: set `contact_email` (sent to Crossref and OpenAlex as a
   courtesy, nothing else), replace the example `phrases` under `openalex-keywords` with
   ten to twenty phrases from their field, and add or remove working paper series and journals.
   Journals need an ISSN; RePEc NEP reports are at `http://nep.repec.org/rss/nep-XXX.rss.xml`.
7. **First run.** `uv run radar run`. The first run fetches the last seven days, screens a few
   hundred abstracts (10-20 minutes), reads the top papers, and posts the first digest as a
   GitHub issue. Open it together and discuss whether the scores look right; adjust the profile.
8. **Schedule.** Mac: `bin/install-launchd.sh 7 30`. Windows:
   `powershell -ExecutionPolicy Bypass -File bin/install-task.ps1 7 30`. Linux:
   `bin/install-cron.sh 7 30`. Each installs a daily job at 07:30 plus a 13:00 retry. The
   machine has to be awake, with the person logged in, at that time.
9. **Explain the daily loop.** Digest arrives by GitHub email. Reply to the email (or comment on
   the issue) with lines like `good: R12 R15`, `bad: R3 too theoretical`,
   `missed: https://...`. Send a paper in by opening an issue with its link. Once in a while
   run `uv run radar review` to let Claude propose profile changes from the ratings.

## Conventions for later sessions

- `data/radar.sqlite`, `digests/`, and `library/` are state and are committed by the daily job.
  Don't edit them by hand.
- `profile.md` and `config/sources.yml` are the only files most people ever need to touch.
- To pull code improvements from the template: `git remote add template
  https://github.com/bsecon/paper-radar-template && git pull template main`.
