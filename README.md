# Zabbix 7.0 Custom (EOL-Free, SAST/SCA-Clean)

Zabbix 7.0 is nearing its official support end-of-life, and its upstream
container images have stopped receiving updates — known vulnerabilities are
no longer being patched upstream. This project builds Zabbix 7.0 from source,
applies the fixes needed to pass SAST/SCA scanning, and repackages it as a
custom, continuously rebuildable set of container images —
`zabbix-server`, `zabbix-web`, `zabbix-agent2`, and `zabbix-proxy` — staying
config/behavior compatible with the official `zabbix/zabbix-*` images.
MySQL is the only supported backend for the main database; `zabbix-proxy` is
the one exception, since its own local buffer database may use SQLite3, same
as the official image of that name — it never touches the main MySQL
database. Zabbix itself stays on the 7.0.x line; only the base images and
this project's own build/scan/publish tooling are actively maintained.

The Zabbix 7.0 source tree is vendored at `sources/zabbix-7.0.32/` (see
"Adding the Zabbix source" below for provenance and how to update it to a
later 7.0.x point release).

## The build/release tooling layer

This repository's own code (everything except the eventual Zabbix source) is
the automation that takes a Zabbix source tree from build through to a
scanned, published image. It implements six components:

- **VulnerabilityRegistry** (`release_tools/models.py`,
  `release_tools/registry.py`) — the CVE/GHSA triage ledger: register a
  vulnerability, issue a time-boxed waiver when no fix is published yet, and
  track waiver expiry. Persisted to `data/vulnerability-registry.yaml`.
- **ScanRunner** (`release_tools/gate.py`, `scripts/scan-sca.sh`,
  `scripts/scan-sast.sh`) — normalizes Trivy (SCA), Semgrep, and cppcheck
  (SAST) tool output into a common `Finding` shape and evaluates the
  pass/fail gate against the registry's current waiver state.
- **SecretScanner** (`scripts/scan-secrets.sh`, `.pre-commit-config.yaml`) —
  gitleaks, run both pre-commit (git diff) and in CI (git diff + the built
  image's filesystem layers); both must come back clean.
- **BuildPipeline** (`docker/*/Dockerfile`, `scripts/build-images.sh`) —
  builds the 4 in-scope components (server/web/agent2/proxy; no
  java-gateway) on Alpine, amd64 only, MySQL only (proxy's local buffer may
  use SQLite3).
- **CompatibilityTestRunner** (`compose.yml`, `scripts/compat-test.sh`) —
  brings the stack up via `docker compose` and checks official-image
  environment variable/volume compatibility, logging `docker stats
  --no-stream` as a reference observation (not itself a release gate).
- **ImagePublisher** (`release_tools/tagging.py`, `scripts/push-images.sh`) —
  generates the `tamacat/<repository>:<version>-alpine-b<YYYYMMDD>`
  tag (never a floating tag such as `latest`; same repositories and tag format as
  `zabbix-5.0-custom`), enforces the 4-condition
  publish gate (SCA pass, SAST pass, compatibility pass, secrets clean) plus
  an explicit self-review confirmation before `docker push`, then attempts
  cosign keyless signing and SBOM attestation against the published registry
  digest (CI-only; skipped with a warning outside a GitHub Actions OIDC
  context).

## Adding the Zabbix source

The Dockerfiles and scripts reference `${ZABBIX_SRC_DIR}` (build arg / env
var, default `sources/zabbix-7.0.32`) as the location of the buildable
Zabbix 7.0 source tree, relative to this directory. It is vendored directly
(committed, not a nested git submodule), matching the layout already used by
the sibling `zabbix-5.0-custom` project.

The vendored tree was obtained from Zabbix's official source distribution
and its integrity verified against the official SHA-256 checksum before
extracting:

```bash
curl -sSL -o zabbix-7.0.32.tar.gz \
  https://cdn.zabbix.com/zabbix/sources/stable/7.0/zabbix-7.0.32.tar.gz
curl -sSL -o zabbix-7.0.32.tar.gz.sha256 \
  https://cdn.zabbix.com/zabbix/sources/stable/7.0/zabbix-7.0.32.tar.gz.sha256
sha256sum -c zabbix-7.0.32.tar.gz.sha256   # must print "OK" before extracting
tar -xzf zabbix-7.0.32.tar.gz -C sources/
```

To move to a later 7.0.x point release, repeat the same download-and-verify
steps for the new version, replace `sources/zabbix-7.0.32/` with the new
tree, commit that unmodified tree on its own, point `data/upstream-import-ref`
at that commit (the SAST gate diffs against it), regenerate the SAST baseline
(`./scripts/scan-sast.sh --update-baseline`), and update
`ZABBIX_VERSION`/`ZABBIX_SRC_DIR` in `.env` and `.env.example` accordingly
(never upgrade past the 7.0.x line — see `docs/CONTRIBUTING.md`). Override
`ZABBIX_SRC_DIR` if you place the source somewhere else.

## Running the tools

```bash
cp .env.example .env   # fill in DB_SERVER_HOST / MYSQL_PASSWORD / etc.

# Tests (do not require the Zabbix source to be present)
python3 -m pytest tests -q        # release_tools/ unit tests
bats tests/scripts                # scripts/ tests (requires bats-core)
./scripts/ui-test.sh              # Web admin UI regression tests against a built stack
                                  # (builds + starts an isolated stack; see docs/CONTRIBUTING.md)

# VulnerabilityRegistry CLI
python3 -m release_tools.cli register-cve --cve-id CVE-2026-00001 \
  --component zabbix-server --severity Critical
python3 -m release_tools.cli generate-tag --component zabbix-server \
  --zabbix-version 7.0.32 --build-date "$(date -u +%Y%m%d)" --arch amd64
```

Once the Zabbix source is present:

```bash
./scripts/build-images.sh      # build + tag all 4 components
./scripts/scan-sca.sh   <tag>  # Trivy SCA scan + gate
./scripts/scan-go-vuln.sh <agent2-tag>   # govulncheck on the agent2 binary + gate (needs Go 1.26+)
./scripts/scan-sast.sh         # Semgrep + cppcheck SAST: files changed since the upstream
                                # import, new findings only (--scope full for the whole tree;
                                # see docs/CONTRIBUTING.md "Security scanning")
./scripts/scan-secrets.sh <tag> [<tag> ...]   # gitleaks, git diff + image layers
./scripts/compat-test.sh       # docker compose up + compatibility checklist
./scripts/ci-pipeline.sh       # runs the checks above in order (build
                                # through the BR3.1 publish-gate check), stopping
                                # at the first failing gate
./scripts/push-images.sh --tag <tag> --sca Pass --sast Pass \
  --compat Pass --secret Clean   # publish gate + self-review + docker push
```

See [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) for the commit-message
CVE/GHSA traceability convention and the code-style tracks (patches to
upstream Zabbix source vs. this project's own build/CI layer).

## Docker Hub

Pre-built images are published to the same Docker Hub repositories that
`zabbix-5.0-custom` uses, named after the official `zabbix/*` images, so a 7.0
tag sits next to the 5.0 ones in each repository:

| Component | Docker Hub |
|---|---|
| zabbix-server (MySQL) | [tamacat/zabbix-server-mysql](https://hub.docker.com/r/tamacat/zabbix-server-mysql) |
| zabbix-web (nginx, MySQL) | [tamacat/zabbix-web-nginx-mysql](https://hub.docker.com/r/tamacat/zabbix-web-nginx-mysql) |
| zabbix-agent2 | [tamacat/zabbix-agent2](https://hub.docker.com/r/tamacat/zabbix-agent2) |
| zabbix-proxy (SQLite3) | [tamacat/zabbix-proxy-sqlite3](https://hub.docker.com/r/tamacat/zabbix-proxy-sqlite3) |

Tag format: `<zabbix-version>-alpine-b<build-date>`, the same for all four images
(there are no floating tags such as `latest`), e.g.:

```bash
docker pull tamacat/zabbix-server-mysql:7.0.32-alpine-b20260925
```

Images are signed with cosign (keyless) and carry a CycloneDX SBOM attestation;
publishing waits for approval on the `production` GitHub Environment.

## Standalone agent2 binaries (GitHub Releases)

`zabbix_agent2` is also published as plain binaries, for hosts where a
container is not an option. Each [Release](../../releases) (tag
`agent2-<zabbix-version>-b<build-date>`, e.g. `agent2-7.0.32-b20261017`)
carries:

| File | Contents |
|---|---|
| `zabbix_agent2-<version>-b<date>-linux-amd64.tar.gz` | Linux x86_64, **fully static** (musl) — runs on any distribution, no shared libraries needed |
| `zabbix_agent2-<version>-b<date>-windows-amd64.zip` | Windows 64-bit, OpenSSL/PCRE2/libiconv linked in — no extra DLLs |
| `SHA256SUMS` | checksums of the two archives |
| `*.sigstore.json` | keyless cosign signatures (Sigstore bundles) for each file above |

Each archive holds the agent, its default configuration, the per-plugin
configuration, the licenses, and a `README.txt` with the install steps. The
layout follows the official packages (`sbin/` or `bin/`, `conf/`).

```bash
# Verify, then unpack (Linux)
sha256sum -c SHA256SUMS --ignore-missing
cosign verify-blob --bundle SHA256SUMS.sigstore.json \
  --certificate-identity-regexp '^https://github.com/tamacat/zabbix-7.0-custom/.github/workflows/agent2-binaries.yml@' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com SHA256SUMS
tar -xzf zabbix_agent2-7.0.32-b20261017-linux-amd64.tar.gz
```

On Windows, edit `conf\zabbix_agent2.win.conf`, then in an elevated prompt
run `bin\zabbix_agent2.exe -c <absolute path to the .conf> --install` and
`--start` (full steps are in the archive's `README.txt`). The Windows
executable is not code-signed, so SmartScreen may warn on first run.

Things to know:

- **Build.** `scripts/build-agent2-binaries.sh` builds both binaries in
  containers (`docker/agent2-binaries/Dockerfile`) and writes the archives to
  `dist/`. The Windows `.exe` is cross-compiled on Alpine with MinGW-w64,
  following the upstream `build/mingw/Makefile` step by step
  (`docker/agent2-binaries/build-windows.sh`); OpenSSL, PCRE2 and libiconv for
  it are built from source tarballs pinned by version and SHA-256 in the
  Dockerfile. `tests/test_agent2_binaries.py` checks that the object list stays
  in step with the upstream Makefile when the Zabbix source is updated.
- **Scanning.** `scripts/scan-agent2-binaries.sh` runs `govulncheck` on both
  binaries (Linux ELF and Windows PE) and applies the same waiver-aware gate as
  the images. govulncheck covers the **Go** code only. The statically linked C
  libraries (OpenSSL, PCRE2, libiconv in the Windows build; the Alpine static
  libraries in the Linux build) are not seen by it or by Trivy, so their
  versions are pinned in `docker/agent2-binaries/Dockerfile` and must be
  checked against upstream security advisories and bumped on a schedule — do
  this alongside the periodic base-image rebuild.
- **Go version.** `GOTOOLCHAIN` is pinned to the same value as
  `docker/agent2/Dockerfile` (a test enforces it), because the Go standard
  library is compiled into both.
- **Linux limits.** Static musl binary: users and groups come from
  `/etc/passwd` and `/etc/group` (no NSS modules such as LDAP/SSSD). There is no
  systemd unit and no deb/rpm package.
- **Publishing.** The [Agent2 binaries](.github/workflows/agent2-binaries.yml)
  workflow builds and tests on every relevant pull request; a manual run with
  `publish` ticked also signs the files and creates the Release, after approval
  on the `production` GitHub Environment (the same self-review gate as the
  images). The workflow's own gates are govulncheck plus smoke tests (the Windows
  binary is run on a real Windows runner); source SAST and secret scanning run in
  `ci-release.yml`, so check that it is green for the commit you release from.

## Configuring zabbix-proxy

The proxy image takes the same environment variables as the official
`zabbix/zabbix-proxy-sqlite3` image (and as `zabbix-5.0-custom`'s proxy), and
turns them into `zabbix_proxy.conf` at start. A variable that is unset or empty
leaves the parameter at Zabbix's default.

| Variable | Parameter / meaning |
|---|---|
| `ZBX_SERVER_HOST` | `Server`; default `zabbix-server`. Append a port as `host:port` (`ZBX_SERVER_PORT` also works, but only when set) |
| `ZBX_HOSTNAME` | `Hostname`, **must match the proxy name registered on the server**; default `zabbix-proxy-sqlite3`. It also names the SQLite buffer, `db_data/<name>.sqlite` |
| `ZBX_PROXYMODE` | `0` active (default), `1` passive |
| `ZBX_TLSCONNECT`, `ZBX_TLSACCEPT`, `ZBX_TLSPSKIDENTITY`, `ZBX_TLS*FILE`, `ZBX_TLSPSK`, `ZBX_TLSCERT`, ... | TLS to the server. Give files by path (relative paths are looked up in the `enc` volume) or give the content itself |
| `ZBX_PROXYCONFIGFREQUENCY`, `ZBX_HEARTBEATFREQUENCY`, `ZBX_DATASENDERFREQUENCY`, `ZBX_START*`, `ZBX_*CACHESIZE`, `ZBX_TIMEOUT`, `ZBX_DEBUGLEVEL`, ... | the matching `zabbix_proxy.conf` parameters, including the 7.0 additions (`ZBX_STARTAGENTPOLLERS`, `ZBX_STARTHTTPAGENTPOLLERS`, `ZBX_STARTSNMPPOLLERS`, `ZBX_STARTBROWSERPOLLERS`, `ZBX_WEBDRIVERURL`, `ZBX_MAXCONCURRENTCHECKSPERPOLLER`, `ZBX_PROXYBUFFERMODE`, `ZBX_PROXYMEMORYBUFFERSIZE`, `ZBX_PROXYMEMORYBUFFERAGE`) |
| `ZBX_CONFIGFREQUENCY` (the 6.0 name) | read as `ZBX_PROXYCONFIGFREQUENCY`, because 7.0 deprecates `ConfigFrequency`. `ZBX_STARTHISTORYPOLLERS` is gone in 7.0 and is reported and ignored |
| `ZBX_LOADMODULE` | comma-separated modules from the `modules` directory |

The legacy name `ZBX_PROXY_HOSTNAME` (what this project's `compose.yml` and
`.env` use) still works as an alias for `ZBX_HOSTNAME`; the official name wins
when both are set. Any other `ZBX_*` variable that the image does not act on
(Java gateway, IPMI, ODBC, SNMP traps, SSH are not built in) is reported with a
warning at start instead of being ignored silently, and `ZBX_*` is removed from
the environment `zabbix_proxy` runs in (set `ZBX_CLEAR_ENV=false` to keep it).
For ICMP checks the container needs `NET_RAW` (`compose.yml` adds it).

## Official environment variables (server, agent2, web)

Like the proxy, the other images take the variables of the official
`zabbix/zabbix-*` 7.0 images; an unsupported `ZBX_*` variable is warned about
at start instead of being ignored silently.

- **zabbix-server**: `DB_SERVER_HOST/PORT`, `MYSQL_USER/PASSWORD/DATABASE` (and `*_FILE`
  for the secrets), DB TLS (`ZBX_DBTLSCONNECT`, `ZBX_DBTLS*FILE`), server TLS, every
  `ZBX_<Parameter>` of `zabbix_server.conf` that is built in (including the 7.0 additions:
  `ZBX_STARTAGENTPOLLERS`, `ZBX_STARTHTTPAGENTPOLLERS`, `ZBX_STARTSNMPPOLLERS`,
  `ZBX_STARTCONNECTORS`, `ZBX_STARTBROWSERPOLLERS`, `ZBX_WEBDRIVERURL`,
  `ZBX_MAXCONCURRENTCHECKSPERPOLLER`, `ZBX_ENABLEGLOBALSCRIPTS`, `ZBX_ALLOWSOFTWAREUPDATECHECK`),
  `ZBX_LOADMODULE`, Vault (`ZBX_VAULT`, `ZBX_VAULTURL`, `ZBX_VAULTDBPATH`, `ZBX_VAULTPREFIX`,
  `ZBX_VAULTTLSCERTFILE`, `ZBX_VAULTTLSKEYFILE`, `VAULT_TOKEN`; as in the official image the
  Vault settings are used only when `ZBX_VAULT` and `ZBX_VAULTURL` are both set, and with
  `ZBX_VAULTDBPATH` the DB user and password come from Vault, so `MYSQL_PASSWORD` is not needed),
  and HA
  (`ZBX_HANODENAME`, `ZBX_AUTOHANODENAME`, `ZBX_NODEADDRESS`, `ZBX_AUTONODEADDRESS`). The config
  file is `0600` because it holds the DB password; the server starts as root only to
  fix ownership, then runs as `zabbix`. `fping` is included (give the container `NET_RAW`).
- **zabbix-agent2**: `ZBX_HOSTNAME`, `ZBX_SERVER_HOST/PORT`, `ZBX_PASSIVESERVERS`,
  `ZBX_ACTIVESERVERS`, `ZBX_PASSIVE_ALLOW`, `ZBX_ACTIVE_ALLOW`, `ZBX_ENABLEPERSISTENTBUFFER`,
  `ZBX_ENABLESTATUSPORT`, `ZBX_ALLOWKEY/DENYKEY`, TLS (path or content, and the cipher suites
  `ZBX_TLSCIPHER*`), `ZBX_HEARTBEAT_FREQUENCY`, and the other agent2 parameters as
  `ZBX_<Parameter>`. `ZBX_ALIAS` (the official image does not allow it either: mount a file
  with `Alias=` lines instead), `ZBX_ENABLEREMOTECOMMANDS` (deprecated; use `ZBX_ALLOWKEY` /
  `ZBX_DENYKEY`) and `ZBX_EVENTLOGMAXLINESPERSECOND` (Windows only) are reported and ignored.
- **zabbix-web**: `DB_SERVER_HOST/PORT`, `MYSQL_*` (and `*_FILE`), `ZBX_SERVER_HOST/PORT/NAME`,
  `PHP_TZ`, PHP limits (`ZBX_MAXEXECUTIONTIME`, `ZBX_MEMORYLIMIT`, `ZBX_POSTMAXSIZE`,
  `ZBX_UPLOADMAXFILESIZE`, `ZBX_MAXINPUTTIME`, `ZBX_SESSION_NAME`), `PHP_FPM_PM*`, DB TLS
  (`ZBX_DB_ENCRYPTION`, `ZBX_DB_*_FILE`, `ZBX_DB_VERIFY_HOST`, `ZBX_DB_CIPHER_LIST`),
  `DB_DOUBLE_IEEE754`, Vault (`ZBX_VAULT`, `ZBX_VAULTURL`, `ZBX_VAULTDBPATH`, `ZBX_VAULTPREFIX`,
  `ZBX_VAULTCERTFILE`, `ZBX_VAULTKEYFILE`, `ZBX_VAULTCACHE`, `VAULT_TOKEN`), history storage,
  SSO (`ZBX_SSO_SP_KEY/SP_CERT/IDP_CERT` and `ZBX_SSO_SETTINGS`), `ZBX_ALLOW_HTTP_AUTH`,
  `ENABLE_WEB_ACCESS_LOG`, `EXPOSE_WEB_SERVER_INFO`, `HTTP_INDEX_FILE`,
  `WEB_REAL_IP_FROM/HEADER`, and `ZBX_DENY_GUI_ACCESS` / `ZBX_GUI_ACCESS_IP_RANGE` /
  `ZBX_GUI_WARNING_MSG`. HTTPS: mount `ssl.crt` and `ssl.key` (optionally `dhparam.pem`)
  at `/etc/ssl/nginx` and the image also listens on 8443.

## First-time database setup (manual)

Unlike the official `zabbix/zabbix-server-mysql` image, `docker/server/entrypoint.sh`
does **not** auto-load the Zabbix schema into an empty database on first boot.
Before `zabbix-server` can start against a fresh MySQL database, load the
three SQL files from the vendored source once, in this order:

```bash
mysql -h "$DB_SERVER_HOST" -u "$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" \
  < sources/zabbix-7.0.32/database/mysql/schema.sql
mysql -h "$DB_SERVER_HOST" -u "$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" \
  < sources/zabbix-7.0.32/database/mysql/images.sql
mysql -h "$DB_SERVER_HOST" -u "$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" \
  < sources/zabbix-7.0.32/database/mysql/data.sql
```

**The database must exist with `utf8mb4` character set and `utf8mb4_bin`
collation before loading `schema.sql`.** None of its `CREATE TABLE` statements
carry a per-table `CHARACTER SET`/`COLLATE` clause, so every table silently
inherits whatever the database's default was at creation time. MySQL 8's own
server default is `utf8mb4_0900_ai_ci`, not `utf8mb4_bin` — load the schema
into a database created with that default and the Zabbix frontend refuses to
start ("Unsupported charset or collation for tables: ..."), confirmed against
a real fresh load. Create it explicitly first if your MySQL doesn't already
default to `utf8mb4_bin`:

```sql
CREATE DATABASE zabbix CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
```

If the database user lacks the `SUPER` privilege and binary logging is
enabled (common on managed/shared MySQL, and on a stock `mysql:8.0` test
instance), `schema.sql` fails partway through creating trigger/function
objects (`ERROR 1419 ... SUPER privilege and binary logging is enabled`).
Either grant `SUPER`, or set `log_bin_trust_function_creators=1` (globally,
or for the session loading the schema) before running it. If a partial load
already happened, drop and recreate the database before retrying — `schema.sql`
is not safe to re-run over a partially-loaded one (`ERROR 1050 ... already exists`).

This is a deliberate scope boundary, not an oversight still to be closed:
official-image-style auto-initialization was considered and declined, to
avoid a container silently reinitializing a database it merely can't yet see
data in. Do this once per fresh database, exactly as you would for any other
first-time Zabbix installation.

### Local verification database: `dev-mysql` (on by default)

For local verification only (never used in production), a throwaway MySQL
service with all of the above already handled — correct charset/collation,
the `SUPER`/binary-logging workaround, and loading the three SQL files in the
right order via the standard `docker-entrypoint-initdb.d` mechanism — is
defined under the `dev` Compose profile. `.env.example` sets
`COMPOSE_PROFILES=dev` and points `DB_SERVER_HOST` at it, so the whole stack
comes up with zero manual steps:

```bash
cp .env.example .env
docker compose up -d   # brings up dev-mysql (one-time schema load happens
                        # automatically) alongside server/web/agent2/proxy
```

`zabbix-server`/`zabbix-web` have no explicit `depends_on` ordering against
`dev-mysql`'s schema load (which takes on the order of a minute on first
run), but `zabbix_server`'s own built-in reconnect loop (`database is down:
reconnecting in 10 seconds`) picks it up as soon as it's ready — no restart
needed, confirmed against a real fresh `docker compose up -d`.

**For production**, edit `.env`: remove or repoint `COMPOSE_PROFILES`, and
point `DB_SERVER_HOST` (plus `MYSQL_PASSWORD`) at your own existing MySQL
instance instead — this project never containerizes, upgrades, or migrates
that database.

`dev-mysql` also points the pre-seeded "Zabbix server" host's agent
interface at the `zabbix-agent2` container instead of `data.sql`'s same-host
default of `zabbix-server`, which this project's split-container topology
doesn't match (confirmed against a real fresh load — without it, the Web UI
shows "Zabbix agent is not available" indefinitely). See
[`docker/dev-mysql/init/00-load-zabbix-schema.sh`](docker/dev-mysql/init/00-load-zabbix-schema.sh).

## Continuous Integration

[`​.github/workflows/ci-release.yml`](.github/workflows/ci-release.yml) runs on
every push/PR to `main`, on a weekly schedule (Monday 03:00 UTC, for the base
image rebuild/rescan practice above), and on manual dispatch. It re-runs the
unit test suite, `scripts/ci-pipeline.sh`, and — after a required manual
approval on the `production` GitHub environment (this project's self-review
gate) — `scripts/push-images.sh` for each component, then signs the published
digest with cosign (keyless, GitHub OIDC) and attaches its SBOM.

Before the workflow can publish, this repository's own GitHub settings need
two one-time additions: a `production` environment with the repository owner
set as a required reviewer (this is the self-review gate), and
`DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN` repository secrets scoped to push
access only.

## Ongoing maintenance

The base image (Alpine) is rebuilt and rescanned periodically, not just once
at first release — this project exists specifically because the official
images stopped receiving these updates, so this practice is required, not
optional. The release gate always checks against the current CVE database
at gate-evaluation time rather than relying on scan results from whenever
the image was originally built.

### PHP in `zabbix-web` is built from source

The `zabbix-web` image does not use Alpine's `php85` packages: PHP is compiled
from the official tarball in `docker/web/Dockerfile` (pinned by version and
SHA-256, which the build verifies), so a PHP security release can be taken the
day it is published instead of whenever Alpine packages it. The extension set is
the same one the Alpine packages provided and Zabbix needs (and nothing else —
no curl, sodium, sqlite3, …); `tests/test_web_php.py` keeps the list, the
paths the entrypoint relies on, and the runtime libraries in step.

Consequences to know about:

- **Trivy cannot see PHP's own vulnerabilities** (it matches Alpine packages,
  and this PHP is not one). Instead,
  [`scripts/check-php-version.sh`](scripts/check-php-version.sh) compares the
  pinned `PHP_VERSION` with the latest release of the same series on php.net,
  and the weekly CI run (`php-version` job) fails when a newer one exists.
- **Updating PHP** is a manual step: take the new version and its SHA-256 from
  `https://www.php.net/releases/index.php?json&version=8.5`, set `PHP_VERSION`
  and `PHP_SHA256` in `docker/web/Dockerfile`, rebuild, and check that the
  Zabbix front end's setup prerequisites page and `scripts/compat-test.sh` pass.
- The Alpine libraries PHP links against (libxml2, OpenSSL, libpng, …) are still
  ordinary packages: the build's `apk upgrade` keeps them current and Trivy
  scans them.

## License

AGPL-3.0, matching upstream Zabbix 7.0's own license (Zabbix changed from GPL-2.0 to
AGPL-3.0 with 7.0) — see [LICENSE](LICENSE). The tooling in this repository is under the same license.

The AGPL applies to users who reach a modified program over a network (section 13):
the images built here run the Zabbix front end with this repository's patches, so
the corresponding source is this repository (the Zabbix source under `sources/` with
the patches applied, plus the build files). Keep it publicly available alongside
the published images.

## 7.0 build notes (verified against 7.0.32)

- Builder stages need `linux-headers` (`linux/version.h`, used by `proc.c`); added to server/proxy/agent2.
- agent2: 7.0 writes the binary to `src/go/bin/zabbix_agent2` (6.0: `src/go/bin` was the file itself).
- Database TLS: the Alpine mariadb-connector-c (3.4) requires a verified TLS connection when no SSL option is set,
  which breaks plain or self-signed-cert MySQL. `src/libs/zbxdb/db.c` carries a patch (same as 6.0) that, when
  `DBTLSConnect` is unset, sets `MYSQL_OPT_SSL_ENFORCE=0` and `MYSQL_OPT_SSL_VERIFY_SERVER_CERT=0`. Verified against
  MySQL 8.0 with and without TLS. For real TLS set `ZBX_DBTLSCONNECT=verify_full` + `ZBX_DBTLSCAFILE`
  (MariaDB's connector supports only `required` / `verify_full`).
