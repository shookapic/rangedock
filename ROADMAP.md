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

## Where we are: v0.1

Shipped: local image build; named workspaces; create, enter, start, run, list, stop,
remove; persistent host folders; non-root image; Linux host UID/GID mapping; Docker
ownership labels; CI and a real Docker lifecycle test. The current base image reports
about 430 MB on the maintainer's Docker Desktop installation. This is a local image
measurement, not a download-size promise.

Missing for everyday use: a one-command open flow, prebuilt images, update handling,
workspace inspection, reusable defaults, VPN, GUI, and a broader tool selection.

## Release sequence

| Release | Outcome | Deliverables | Exit gate |
| --- | --- | --- | --- |
| **v0.2: daily driver** | A new user reaches a shell quickly and understands every workspace. | `open NAME` creates/starts/enters; `--workspace .`; `info NAME`; `restart`; useful Docker diagnostics; consistent errors and help; install through pipx/uv/pip; documented Windows, Linux, and macOS setup. | Fresh user can install and open a lab in under five minutes after Docker is ready. Windows and Linux lifecycle tests pass; macOS gets a documented manual smoke test until CI is available. Removal never deletes host files. |
| **v0.3: maintained images** | No local build needed for normal use. | Public, versioned `base` and `web` images for amd64/arm64; `image list/pull/update`; pinned tool manifest, software bill of materials, vulnerability checks, and provenance; explicit notice that existing containers keep their old image; local custom builds remain supported. | A clean machine pulls and opens an image without compiling tools. Tool versions can be reproduced from a release manifest. Image updates never silently replace a running workspace. |
| **v0.4: repeatable labs** | An operator can recreate a useful setup without Docker flag memorization. | Local profiles and user config; shared read-only resources and user customizations; optional extra mounts and loopback-only port publishing; persistent shell history; a `doctor` report that explains platform limitations. | Two machines can create the same profile and see the same tool versions and workspace layout. Invalid mounts, ports, or profile keys fail before container creation. |
| **v0.5: connected labs** | Common network labs work without configuring the host by hand. | OpenVPN and WireGuard inside isolated containers, with only required capabilities/devices; explicit network modes; connection status and logs; opt-in browser desktop for GUI tools. Implement Linux first, then validate Docker Desktop and macOS behavior. | VPN traffic and DNS behavior are tested in a controlled lab; disconnect/restart works; unsupported host features produce an actionable error. Desktop binds to localhost by default. |
| **v1.0: dependable free workstation** | Stable local product for regular security work. | Supported-platform matrix, upgrade/migration guide, maintained release cadence, accessibility of CLI output, troubleshooting docs, and realistic example labs. | Release gates below pass for two consecutive releases, with no known workspace data-loss bug or critical image vulnerability left unaddressed. |

These are roughly a few months of focused work for a small team, and longer for a
part-time solo maintainer. v0.2 and the image pipeline are the next two investments.

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
