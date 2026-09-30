# Finding and running the repo's linters

The goal is to run **the linters this repo already uses, the way it already runs them**. That
means the same thing CI or the pre-commit hook will run once the PR is open. Don't introduce a
linter the repo doesn't use, and don't install tools globally.

## 1. Find the repo's own entry point first

Check these in order. The first match is usually what CI runs, so it's the most faithful signal:

1. **CI config**: `.github/workflows/*.yml`, `azure-pipelines.yml`, `.gitlab-ci.yml`,
   `bitbucket-pipelines.yml`, `Jenkinsfile`. Look for the lint/format/check step and copy its
   command.
2. **Pre-commit**: `.pre-commit-config.yaml` → `pre-commit run --from-ref <merge-base> --to-ref HEAD`
   (checks only the files the branch changed). Use `pre-commit run --files <changed files>` to
   include uncommitted work.
3. **Task runners**: `package.json` `scripts` (`lint`, `lint:check`, `format:check`, `typecheck`),
   `Makefile` / `justfile` targets (`lint`, `check`), `tox.ini` / `noxfile.py` lint envs,
   `composer.json` scripts, `Taskfile.yml`.
4. **Tool configs with no wrapper.** Use the table below.

A monorepo can have several of these, one per package. Run the linter for each package the branch
touched, from that package's directory.

## 2. Tool table (check mode first, fix mode for later)

| Ecosystem | Config signals | Check (report only) | Fix (only after approval) |
|---|---|---|---|
| JS/TS | `eslint.config.*`, `.eslintrc*`, `eslintConfig` in package.json | `npx --no-install eslint <files>` | `... --fix` |
| JS/TS | `biome.json` | `npx --no-install biome check <files>` | `... --write` |
| JS/TS format | `.prettierrc*`, `prettier` in package.json | `npx --no-install prettier --check <files>` | `... --write` |
| Python | `ruff` in `pyproject.toml`/`ruff.toml` | `ruff check <files>` + `ruff format --check <files>` | `ruff check --fix`, `ruff format` |
| Python | `.flake8`, `setup.cfg [flake8]` | `flake8 <files>` | (none; hand-fix or use formatter) |
| Python | `black` / `isort` in pyproject | `black --check <files>`, `isort --check-only <files>` | drop `--check` |
| Python | `pylint` in config / `.pylintrc` | `pylint <files>` | (hand-fix) |
| C#/.NET | `.editorconfig` + `*.sln`/`*.csproj` | `dotnet format --verify-no-changes --include <files>` | `dotnet format --include <files>` |
| Go | `.golangci.yml` | `golangci-lint run --new-from-rev=<merge-base>` | `... --fix` |
| Go | (always) | `gofmt -l <files>`, `go vet ./<pkgs>` | `gofmt -w` |
| Rust | `Cargo.toml` | `cargo clippy -- -D warnings`, `cargo fmt --check` | `cargo clippy --fix`, `cargo fmt` |
| Java/Kotlin | checkstyle/spotless/ktlint in Gradle/Maven | `./gradlew spotlessCheck` / `ktlint <files>` / `mvn checkstyle:check` | `spotlessApply` / `ktlint -F` |
| Ruby | `.rubocop.yml` | `bundle exec rubocop <files>` | `... -a` |
| PHP | `phpcs.xml`, `.php-cs-fixer.php` | `vendor/bin/phpcs <files>` / `php-cs-fixer fix --dry-run <files>` | drop `--dry-run` / `phpcbf` |
| Shell | any `*.sh` changed | `shellcheck <files>` (only if already installed) | (hand-fix) |
| SQL | `.sqlfluff` | `sqlfluff lint <files>` | `sqlfluff fix` |
| Markdown | `.markdownlint*` | `npx --no-install markdownlint <files>` | `... --fix` |

Run tools through the project's environment so you get the pinned version: `npx --no-install`,
`uv run`, `poetry run`, `pipenv run`, `bundle exec`, `vendor/bin/`, `./gradlew`.

## 3. Scope to the branch

- Pass the **changed files** (from `git diff --name-only --diff-filter=d <merge-base>` plus untracked
  files you intend to commit) instead of linting the whole repo. It's faster, and the output is
  about this PR.
- Some linters can scope to new code by themselves (`golangci-lint --new-from-rev`,
  `pre-commit --from-ref`). Prefer that when it's available.
- Linting a whole file will also surface **pre-existing** issues on lines the branch didn't touch.
  Split the results:
  - **Introduced**: the issue is on a line the branch added or changed. Get the added line ranges
    from `git diff -U0 <merge-base> -- <file>` (the `+start,count` in each `@@` header). Report
    these as blockers if the linter treats them as errors, otherwise as warnings.
  - **Pre-existing in touched files**: report as info. Don't make fixing them part of this PR
    unless the user wants to, because unrelated churn makes the PR harder to review.

## 4. When the linter can't run

- **Dependencies not installed** (`node_modules/` missing, venv missing, `npx --no-install`
  fails): don't install them silently. Report "lint not run: dependencies not installed" and offer
  the repo's install command (`npm ci`, `uv sync`, `dotnet restore`, ...). Run it only if the user
  says yes.
- **No linter configured**: report "no linter configured in this repo" and move on. Don't choose
  one for them. The scan script and the review still cover the most common problems.
- **Linter crashes or config error**: report the first few lines of the error. A broken lint setup
  is itself worth telling the user about, because CI will probably hit it too.
