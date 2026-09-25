# RangeDock roadmap

Planning snapshot: September 2026. Order and exit criteria matter more than dates.

## Product goal

Make a security lab feel as easy to open as a terminal: one command, a ready toolkit,
an isolated container, and files that remain on the host. RangeDock should be fast,
predictable, and usable on Linux, Windows, and macOS. The free local CLI remains MIT
licensed, including commercial use. Paid services may come later for teams that need
managed distribution and administration.

This is an independent product, not an Exegol image or wrapper fork. Exegol's current
Workstation combines a Docker wrapper, curated images, offline resources, VPN, desktop,
and more. RangeDock should reach comparable **daily workflow quality** before claiming
anything like catalog or feature parity. Copying hundreds of tools into one image would
make the first release slower and harder to maintain.

## Where we are: v0.3.0

Shipped: named workspaces and persistent host folders; CLI lifecycle commands;
non-root images; Linux host UID/GID mapping; Docker ownership labels; local image
builds; published base, web, and desktop images; an opt-in localhost browser desktop;
user-installed Burp; and opt-in OpenVPN with scoped device/capability access. The base
image measured about 566 MB and the web image about 4.26 GB locally on the maintainer's
Docker Desktop. These are local measurements, not compressed download sizes.

Since then: saved VPN profiles, an interactive lab console with local completion and
history, and a per-image tool manifest (see [SPEC.md](SPEC.md)).

Missing for broader use: WireGuard, saved workspace profiles, persistent desktop settings
across container recreation, image vulnerability gates, VPN DNS verification, and a
supported-platform benchmark matrix.

## Release sequence

| Release | Outcome | Deliverables | Exit gate |
| --- | --- | --- | --- |
| **v0.2: daily driver** | A new user reaches a shell quickly and understands every workspace. | `open NAME` creates/starts/enters; `--workspace .`; `info NAME`; `restart`; useful Docker diagnostics; consistent errors and help; install through pipx/uv/pip; documented Windows, Linux, and macOS setup. | Fresh user can install and open a lab in under five minutes after Docker is ready. Windows and Linux lifecycle tests pass; macOS gets a documented manual smoke test until CI is available. Removal never deletes host files. |
| **v0.3: images and connected desktop** | No local build needed for normal use; GUI and OpenVPN labs can be opened on demand. | Public versioned `base`, `web`, and `desktop` images for amd64/arm64; `image list/pull/update`; SBOM and provenance attestations; opt-in OpenVPN; localhost browser desktop; user-installed Burp; existing containers keep their old image. | A clean machine pulls and opens an image without compiling tools. A local OpenVPN tunnel and desktop restart work on the maintainer's Docker Desktop. Published images are anonymously pullable. |
| **v0.3.x: image hardening** | Published image contents are auditable and updates are routine. | Pinned tool manifest, vulnerability checks, compressed size reporting, and a clean host pull test in CI. | A release can be tied to its tool versions and image digest, and critical image findings block publication. |
| **v0.4: repeatable labs** | An operator can recreate a useful setup without Docker flag memorization. | Local profiles and user config; shared read-only resources and user customizations; optional extra mounts and loopback-only port publishing; persistent shell history; a `doctor` report that explains platform limitations. | Two machines can create the same profile and see the same tool versions and workspace layout. Invalid mounts, ports, or profile keys fail before container creation. |
| **v0.5: network and desktop maturity** | Connected labs work predictably across supported hosts. | WireGuard, connection-aware VPN status, DNS and route tests, explicit network modes, authenticated desktop sessions, persistent GUI settings, and platform-specific diagnostics. | VPN traffic and DNS behavior pass controlled tests on each supported host; unsupported host features produce an actionable error. |
| **v1.0: dependable free workstation** | Stable local product for regular security work. | Supported-platform matrix, upgrade/migration guide, maintained release cadence, accessibility of CLI output, troubleshooting docs, and realistic example labs. | Release gates below pass for two consecutive releases, with no known workspace data-loss bug or critical image vulnerability left unaddressed. |

These are roughly a few months of focused work for a small team, and longer for a
part-time solo maintainer. Image hardening and repeatable lab configuration are the next investments.

## Performance and reliability gates

Measure on published reference machines with Docker already running and images cached;
report Linux and Docker Desktop separately. Record the command, OS, Docker version,
architecture, image digest, and 30-run median/p95. Network download time is a separate
metric.

- New `open` to shell prompt: target p95 under 5 seconds on Linux and under 10 seconds
  on Windows/macOS reference machines.
- Re-enter a running workspace: target p95 under 2 seconds on Linux and under 3 seconds
  on Windows/macOS reference machines.
- `base` image: target under 1 GB local image size; publish compressed pull size too.
  Specialized images can be larger, with sizes visible before download.
- Opening an existing workspace must work offline. `stop` and `remove` must preserve
  host files. Failed create/update operations must leave an understandable state.
- Every release runs unit tests plus real Docker create, shell/command, mount write,
  restart, stop, and remove checks. Windows and macOS claims require host smoke tests.

Performance is a user-facing promise only after benchmarks exist; these are targets.

## Free product and possible paid product

**Free forever:** local CLI, all local container lifecycle commands, public images,
custom images, local profiles, workspace mounts, VPN, desktop, and exportable data.
No account, telemetry requirement, or license check for local work. Keep core code
open so community improvements benefit everyone.

**Possible paid services after v1.0 and user demand:** hosted private image registry
and update channels, organization-approved profiles, shared team setup, SSO/RBAC,
central audit/retention, remote workspace orchestration, and support. Charge for
hosting, maintenance, and coordination rather than making a local lab worse for free
users. Validate this with teams before building billing or an account system.

## Focus and explicit deferrals

- Optimize *time to a useful workspace*, not number of bundled tools. Start with
  maintained `base` and `web` images; add an `internal/AD` image only when tested
  workflows and maintainers justify its size and upkeep.
- Ship no arbitrary community recipe execution or marketplace until there is a trust,
  pinning, and review model. Profiles that can mount host paths or grant capabilities
  need clear warnings and validation.
- Do not promise identical raw network, USB, or Wi-Fi behavior on Docker Desktop:
  container networking and device passthrough differ from native Linux.
- Avoid an AI agent, cloud dashboard, and payment flow while basic open/update/VPN
  workflows still need work.

## Source baseline

This comparison used Exegol's [Workstation overview](https://docs.exegol.com/workstation/),
[wrapper features](https://docs.exegol.com/wrapper/),
[images](https://docs.exegol.com/images/), and
[container profiles](https://docs.exegol.com/wrapper/profiles/) as of September 2026.
RangeDock's roadmap is an independent plan; names, images, code, and assets are not
taken from Exegol.
