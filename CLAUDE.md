# paper-radar: setup guide for Claude Code

This repository was created from the paper-radar template. If the person has opened you here
and asks to set up their radar, walk them through the steps below, one at a time, running the
commands for them where you can and asking only for what you cannot know. Check `README.md`
for how the radar works.

## Setup checklist

1. **Prerequisites.** Check which of these exist: `uv` (`uv --version`), the GitHub CLI
   (`gh --version`), and Claude Code (`claude --version`, or inside the Claude desktop app).
   Install what is missing: `curl -LsSf https://astral.sh/uv/install.sh | sh`;
   `gh` from https://cli.github.com; Claude Code with `curl -fsSL https://claude.ai/install.sh | bash`.
   A Claude subscription (Pro or Max) is needed; no API key.
2. **GitHub login.** `gh auth login`, then `gh auth setup-git`. The repo this folder was cloned
   from is where digests and alerts will be posted as issues. Confirm with `gh repo view`.
3. **Claude login for the headless runs.** `bin/claude-login.sh` opens a browser, stores a
   long-lived token in the macOS keychain, and runs one test call.
4. **Dependencies and check.** `uv sync`, then `uv run radar doctor`: it must show the Claude
   binary, `gh`, and the GitHub repo.
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
8. **Schedule.** `bin/install-launchd.sh 7 30` installs a daily job at 07:30 plus a 13:00 retry.
   Linux: put `bin/daily.sh` in a cron entry instead. The machine has to be awake at that time.
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
