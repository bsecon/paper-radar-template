# paper-radar

Every morning, this tool fetches the new economics working papers and journal articles, asks
Claude to score each one against a one-page description of your research, and posts a short
digest of the few that matter to you. It runs on your own computer, Mac or Windows, under your
Claude subscription. No API key, no server, no access to your email.

Setting it up takes about twenty minutes. Most of that is describing your research.

## What you need

- A **GitHub account** (free). Your copy of the tool, your digests, and your ratings live in a
  private repository there, and the digest reaches you as a GitHub email.
- A **Claude subscription** (Pro or Max). Screening a few hundred abstracts a day uses a modest
  share of a Pro plan.
- A computer that is on and logged in at the time of the daily run.

## What gets installed, and why

Four standard, free programs. None of them changes anything else on your computer; each lives
in its own folder and can be removed again (see "Removing it" below). On Windows, the
installers may ask for an administrator confirmation once.

| Program | What it is | Why the radar needs it |
|---|---|---|
| **Git** | The version-control program behind GitHub. On a Mac it is already there. | Copies your repository to your computer and saves the daily results back to GitHub. |
| **GitHub CLI** (`gh`) | GitHub's command-line program. | Lets the radar post digests as issues in your repository and read your ratings back. |
| **uv** | A small program that runs Python projects. | Installs the radar's Python dependencies into a `.venv` folder inside the repository. If your computer has no Python 3.11 or newer, it downloads one into your home folder. |
| **Claude Code** | Anthropic's command-line program for Claude. On a Mac the Claude desktop app includes it. | The radar calls it to score papers and read PDFs under your subscription. It also does the setup for you. |

Nothing is installed system-wide by the radar itself. Everything it writes is in the
repository folder, plus three small items in your home folder: the login token (macOS keychain,
or `~/.config/paper-radar/token` on Windows), a log file, and the scheduled job.

## What the tool does with your data

- **Reads** public paper feeds (NBER, CEPR, IZA, arXiv, RePEc, Crossref, OpenAlex). It sends
  the contact email from `config/sources.yml` to Crossref and OpenAlex as a courtesy
  identifier, which their terms ask for. Nothing else is sent to them.
- **Sends to Claude** (Anthropic, under your subscription): see the next section for exactly
  what, step by step.
- **Writes to your GitHub repository**: the digests, the database of what it has seen, the
  BibTeX library. The repository is private; only you see it.
- **Does not** read your email, your files outside the repository folder, or anything on
  your computer that it did not create. It does not phone home anywhere else.

### What is sent to Claude, exactly

The radar talks to Claude through Claude Code, the same way a conversation in the Claude app
does, under your subscription. Three steps send text; nothing else does.

1. **Screening** (every morning, Claude Sonnet). Each request contains the scoring
   instructions, your whole `profile.md`, up to eight of your most recent ratings of each kind
   as examples (the rated paper's title, venue, the first 300 characters of its abstract, and
   the note you wrote with the rating, if any), and a dozen new papers: type, venue, title,
   authors, JEL codes, and abstract (cut at 2,000 characters). All of this is public bibliographic
   data except the profile and your rating notes.
2. **Full reads** (up to five a day, plus papers you sent in; Claude Opus). The instructions,
   your `profile.md`, the paper's bibliographic data, and the text of its PDF when it is open
   access (cut at 180,000 characters, roughly 60 pages). Paywalled PDFs are not fetched, so
   those papers are read from the abstract only.
3. **Profile review** (only when you run `radar review` yourself; Claude Opus). Your
   `profile.md` and the full list of your ratings with their notes, so Claude can propose
   changes to the profile.

Keep in mind what the profile is: a page about your research interests, written for you by
Claude Code during setup from your CV and papers. Claude has therefore already seen it, and
the material it came from, before the first screening run. The daily runs send that same
page again every morning, because Claude keeps no memory between calls; they do not add
anything Claude has not seen.

What comes back is stored in your repository: a score, a category, and a two-line reason per
paper, and a structured note per full read. Those are the texts you see in the digest.

Not sent, ever: your emails, your files outside the repository folder, the contents of
GitHub issues beyond the paper link they contain, your GitHub or Claude credentials, or
anything about your computer. The prompts are built in `radar/screen.py`,
`radar/deepread.py`, and `radar/review.py`, in plain text, if you want to read them.

How Anthropic handles the text is governed by the terms of your Claude subscription, the same
as for conversations in the app. One setting matters: in the Claude app under Privacy, the
choice whether your conversations may be used to improve Claude applies to Claude Code as well.
If you would rather your profile and reading never be used that way, turn it off there.

## Start your own

1. On this page click **Use this template** and create a **private** repository under your
   own account.
2. Install the programs above.
   - **Mac**: the [Claude desktop app](https://claude.ai/download), the
     [GitHub CLI](https://cli.github.com), and [uv](https://docs.astral.sh/uv/).
   - **Windows**: open PowerShell and run `winget install Git.Git GitHub.cli astral-sh.uv`, then
     `irm https://claude.ai/install.ps1 | iex` for Claude Code. Afterwards open **Git Bash**
     (installed with Git) for everything that follows; the radar's scripts are written for it.
3. Clone your new repository, open Claude Code in that folder, and say **"set up my radar"**.
   The file `CLAUDE.md` holds the checklist. Claude Code explains each step before doing it,
   asks before it installs or logs in to anything, writes `profile.md` from your CV and a
   couple of your papers, runs the first digest with you, and installs the daily job.

You can also do every step by hand:

```bash
gh auth login && gh auth setup-git   # GitHub login (opens a browser)
uv sync                              # Python dependencies into ./.venv
bin/claude-login.sh                  # Claude login for the daily job (opens a browser)
# edit profile.md and config/sources.yml
uv run radar doctor                  # checks that everything is found
uv run radar run                     # first digest
bin/install-launchd.sh 7 30          # daily at 07:30 on a Mac
powershell -ExecutionPolicy Bypass -File bin/install-task.ps1 7 30   # same, on Windows
```

Windows note: if you run `uv sync` from a terminal inside the Claude desktop app and your
computer has no Python 3.11 or newer, the download fails because the app redirects where
programs may write. Run `export UV_PYTHON_INSTALL_DIR="$HOME/.local/share/uv/python"` first,
or use a normal Git Bash window.

## Removing it

Everything can be undone in a few minutes, in this order:

1. Remove the daily job. Mac: `launchctl bootout gui/$(id -u)/com.paper-radar; launchctl
   bootout gui/$(id -u)/com.paper-radar.retry` and delete the two `com.paper-radar*.plist` files
   in `~/Library/LaunchAgents`. Windows, in PowerShell: `Unregister-ScheduledTask paper-radar;
   Unregister-ScheduledTask 'paper-radar retry'`.
2. Remove the login token. Mac: `security delete-generic-password -s paper-radar-claude-token`.
   Windows: delete the folder `~/.config/paper-radar`.
3. Delete the repository folder on your computer, and the private repository on GitHub
   (repository Settings, bottom of the page).
4. If you want the programs gone too: Windows `winget uninstall Git.Git GitHub.cli astral-sh.uv`
   and delete `~/.local/bin/claude.exe`; Mac delete `~/.local/bin/uv`, `~/.local/bin/claude`,
   and the GitHub CLI however you installed it. A Python that uv downloaded is under
   `~/.local/share/uv/python` and can simply be deleted.

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

## Without uv

uv only manages a virtual environment and the dependency lock. If you already have Python 3.11
or newer and prefer pip:

```bash
python -m venv .venv && source .venv/bin/activate   # Git Bash: source .venv/Scripts/activate
pip install -e .
radar doctor
```

Then replace `uv run radar` with `radar` in `bin/daily.sh` and `bin/claude-login.sh`, with the
virtual environment activated in the scheduled job's shell.

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
