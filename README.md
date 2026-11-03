# paper-radar

A daily radar for new economics papers, screened by Claude against your own research profile
and delivered as a GitHub issue every morning. It runs on your own computer, Mac or Windows,
under your Claude subscription; no API key and no server.

## Start your own in twenty minutes

1. Click **Use this template** at the top of this page and create a **private** repository
   under your account (your profile, digests, and ratings will live there).
2. Install the tools (a Claude Pro or Max subscription is needed):
   - **Mac**: the [Claude desktop app](https://claude.ai/download), the
     [GitHub CLI](https://cli.github.com), and [uv](https://docs.astral.sh/uv/).
   - **Windows**: in PowerShell, `winget install Git.Git GitHub.cli astral-sh.uv`, then
     `irm https://claude.ai/install.ps1 | iex` for Claude Code. Open a new **Git Bash** window
     for everything that follows; the scripts are written for it.

   Clone your new repository.
3. Open Claude Code in the cloned folder and say **"set up my radar"**. `CLAUDE.md` holds the
   checklist; it will log you in, write `profile.md` from your CV and papers, run the first
   digest with you, and install the daily job.

Or do it by hand:

```bash
gh auth login && gh auth setup-git
uv sync
bin/claude-login.sh                 # headless Claude login, token goes to the keychain
# edit profile.md and config/sources.yml
uv run radar doctor
uv run radar run                    # first digest
bin/install-launchd.sh 7 30         # daily at 07:30 on a Mac
powershell -ExecutionPolicy Bypass -File bin/install-task.ps1 7 30   # same, on Windows
```

## What the daily run does

1. **fetches** new working papers (NBER, CEPR, IZA, arXiv econ, nine RePEc NEP field reports,
   and an OpenAlex keyword catch-all over every indexed series and repository) and new
   journal articles (Crossref, by ISSN, abstracts filled from OpenAlex),
2. **takes in** papers you sent by opening an issue, and ratings you left as comments,
3. **screens** every new paper against `profile.md` with Claude Sonnet 5 (structured output, a dozen papers per call),
4. **reads** the top papers and anything you sent in with Claude Opus 5 (full PDF text when open access),
5. **posts** a digest as a GitHub issue (and saves it under `digests/`),
6. **keeps** a library: `library/radar.bib` plus `library/index.md`, PDFs synced locally on demand.

## How Claude is called

By default the LLM steps shell out to Claude Code in headless mode (`claude -p --json-schema ...`),
which runs under your Claude subscription: no API key, no per-token bill. The binary is found on
`PATH` or inside the Claude desktop app. `uv run radar doctor` shows what was detected.

To use the API instead (pay as you go, runs anywhere): `uv sync --extra api`, export
`ANTHROPIC_API_KEY`, and set `backend: api` in `config/sources.yml`.

## If the radar goes quiet

The headless login can expire (it did after two weeks the first time). When every screening call
fails, the run opens a GitHub issue labelled `alert`, which GitHub emails you, and shows a macOS
notification. Fix it with:

```bash
bin/claude-login.sh
```

That runs `claude setup-token` (browser login, long-lived token) and stores the token where the
radar reads it: the macOS keychain (`paper-radar-claude-token`), or `~/.config/paper-radar/token`
on Windows and Linux. The next run closes the alert.

## Scheduling

- **Mac**: `bin/install-launchd.sh 7 30` installs a launchd job; log in `~/Library/Logs/paper-radar.log`.
- **Windows**: `powershell -ExecutionPolicy Bypass -File bin/install-task.ps1 7 30` installs a
  Task Scheduler job that runs the same script in Git Bash; log in
  `~/.local/state/paper-radar/daily.log`. A console window appears briefly while it runs.
- **Linux**: `bin/install-cron.sh 7 30` (crontab); same log location as Windows.

Each installer adds a 13:00 retry slot that only runs when the morning run left work pending.
The job runs when the machine is awake and you are logged in at that time; a missed run starts
as soon as the machine is back, and the seven-day lookback covers days it was off. Run it by hand with `uv run radar run`, or trigger the
launchd job with `launchctl kickstart gui/$(id -u)/com.paper-radar` on macOS.

## Sending a paper in

Open an issue in this repo whose title or body contains a link, DOI, or arXiv id. From the phone:
share the LinkedIn post or the paper page to the GitHub app and create an issue. A tiny GitHub
Action acknowledges it immediately; the next morning's run resolves the paper (Crossref, arXiv,
RePEc mirror, page metadata, OpenAlex title search), comments with what it found, closes the
issue, and includes a full read in that day's digest.

Add the word `missed` anywhere in the issue if the radar should have shown it. That records it as
a positive training example.

From the terminal: `uv run radar add https://... [--missed]`.

## Rating the digest

Comment on the digest issue, one line per rating:

```
good: R12 R15
bad: R3 because too theoretical
missed: https://arxiv.org/abs/2608.17446 found this on LinkedIn
```

Or `uv run radar rate good R12 R15 --note "..."`. The last ratings are shown to the screener as
examples on every run. Once a week (or when you feel like it) run `uv run radar review`: Opus 5
reads all ratings and opens an issue with a proposed diff to `profile.md`; `radar review --apply`
writes it. `uv run radar eval` re-screens every rated paper and reports how many wanted papers
the current profile would show and how many unwanted ones it would hide.

## Library

- `library/radar.bib` grows automatically with every kept paper (sent in, rated good, or above the
  score threshold). Keys look like `shimer2000assortative`.
- `library/index.md` lists kept papers with links and the research note.
- Open-access PDFs are downloaded automatically by the daily run into `library/pdfs/`
  (git-ignored). Set `RADAR_LIBRARY_DIR` in the launchd plist to put them elsewhere, e.g. iCloud.
  `uv run radar library sync` does the same by hand; run it on the university network to get
  paywalled journal PDFs through the proxy.
- `uv run radar search "divorce"` searches titles, abstracts, and notes.

## Configuration

- `profile.md`: what you care about. The most important file.
- `config/sources.yml`: sources, journals (by ISSN), thresholds, models.
- `data/radar.sqlite`: all state, committed and pushed by the daily job.

## Commands

| command | what it does |
|---|---|
| `radar run` | full daily pipeline |
| `radar fetch` | poll sources only |
| `radar intake` | process issues and rating comments |
| `radar screen [--limit N]` | score unscreened papers |
| `radar doctor` | check the Claude binary, GitHub access, and state |
| `radar deepread` | full reads for top papers |
| `radar digest [--no-issue]` | write and post the digest |
| `radar add`, `radar rate`, `radar search`, `radar show R12` | manual interaction |
| `radar library sync\|bib\|index` | library maintenance |
| `radar review [--apply]`, `radar eval` | learn from ratings |
| `radar stats` | counts |

## Usage

Roughly 200-400 abstracts a day in groups of a dozen through Sonnet 5 at low effort, plus up to
five full reads on Opus 5. Under the subscription this counts against your plan's usage; on the
API it is on the order of one dollar a day.

## Updating the code

Improvements land in the template repository. Pull them without touching your state:

```bash
git remote add template https://github.com/bsecon/paper-radar-template
git pull template main
```

## License

MIT. Use it, change it, share it; keep the notice.

## Credits

Built by Bastian Schulz (Aarhus University) with Claude Code. Issues and pull requests to the
template repository are welcome.
