# Releasing Mindmap

The first public release publishes a signed universal macOS desktop app, cross-platform terminal binaries, two agent-plugin packages, and SHA-256 checksums. Windows and Linux desktop packages are intentionally deferred.

## Release controls

The upstream repository protects `main` and `v*` tags with active rulesets. Its `release` environment accepts protected `main` and `v*` tags and requires approval from the maintainer who owns the signing credentials. `main` is permitted only so a manual, non-publishing release preflight can exercise the real signing and notarization path. Fork maintainers must create equivalent controls before adding credentials. GitHub applies environment protection rules before a job can read its environment secrets.

Verify the upstream controls with:

```sh
gh api repos/erd0s/mindmap/environments/release
gh api repos/erd0s/mindmap/environments/release/deployment-branch-policies
gh api repos/erd0s/mindmap/rulesets
```

See GitHub's documentation for [deployment environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments) and [repository rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository).

## Apple signing setup

The Apple Developer Account Holder must create a **Developer ID Application** certificate. Install it in Keychain Access, then export the certificate and its private key as a password-protected `.p12` file. Also create an app-specific password for the Apple ID used by the workflow. Apple's guides cover [Developer ID certificates](https://developer.apple.com/help/account/certificates/create-developer-id-certificates/) and the [notarization workflow](https://developer.apple.com/documentation/Security/customizing-the-notarization-workflow).

After Xcode finishes installing, confirm the required tools and the signing identity:

```sh
xcodebuild -version
xcrun notarytool --help
security find-identity -v -p codesigning
```

Upload these values as `release` environment secrets, not repository secrets:

| Secret | Value |
|---|---|
| `MACOS_CERTIFICATE` | Base64-encoded `.p12` contents |
| `MACOS_CERTIFICATE_PASSWORD` | Export password for the `.p12` |
| `MACOS_SIGNING_IDENTITY` | Full Developer ID Application identity shown by `security find-identity -v -p codesigning` |
| `APPLE_ID` | Apple ID used for notarization |
| `APPLE_TEAM_ID` | Ten-character Apple Developer team ID |
| `APPLE_APP_PASSWORD` | App-specific password |

Run the helper on the Mac whose Keychain contains the identity. The password prompts do not echo, enter shell history, or write to disk:

```sh
./scripts/configure_macos_signing.sh \
  --p12 /path/to/DeveloperIDApplication.p12 \
  --identity "Developer ID Application: Your Name (TEAMID)" \
  --apple-id you@example.com \
  --team-id TEAMID
```

The helper verifies the local identity and GitHub environment, then sends each secret directly to GitHub through standard input. Do not paste a certificate or password into an issue, pull request, command-line argument, or chat.

The release job first builds one Intel and one Apple-silicon binary without secrets and combines them with `lipo`. It then checks the secrets, imports the certificate into an ephemeral keychain, signs with the hardened runtime, notarizes and staples the app, and produces a separately signed, notarized, and stapled DMG. A missing secret fails before signing and notarization.

## Preflight

From a clean checkout:

```sh
npm ci --prefix desktop/frontend
make validate-strict
make audit
go test -race ./...
go vet ./...
git status --short
```

On macOS, also build and inspect the unsigned universal app:

```sh
make macos-preflight
```

Review `CHANGELOG.md`, confirm that the package version and plugin manifests agree, and replace both screenshot placeholders in `docs/images/`.

Run the `release` workflow manually from `main` before creating the version tag. Approve its protected `release` environment only after confirming the run uses the expected commit. The workflow exercises the production signing, notarization, stapling, Gatekeeper, manifest, and attestation steps, then uploads a `release-candidate-VERSION` artifact. A manual run cannot publish a GitHub Release.

## Publish

Complete these steps in order:

1. Rewrite or squash every reachable Git ref so the public history contains no credentials, private hostnames, local project names, or personal paths.
2. Scan the rewritten history for secrets and private identifiers. Inspect the results before continuing.
3. Change the GitHub repository visibility to public.
4. Create and push an annotated version tag only after the preflight and manual functional runbook pass:

```sh
git tag -a v0.3.0 -m "Mindmap 0.3.0"
git push origin v0.3.0
```

Do not push the release tag while this repository is private unless it belongs to an organization on GitHub Enterprise Cloud. [GitHub limits artifact attestations in private and internal repositories to Enterprise Cloud](https://docs.github.com/en/code-security/getting-started/github-security-features#artifact-attestations); public repositories support them on current plans.

The tag starts an independent release gate before GitHub publishes any asset. The workflow rejects a tag that does not match the package version and publishes GitHub build-provenance attestations for the app, plugins, and terminal binaries. Afterward, verify the checksums and attestations, download the DMG on a clean Mac, and repeat the Gatekeeper and notarization checks in the functional runbook.

SHA-256 checksums detect corruption but do not authenticate a release by themselves. With the GitHub CLI installed, verify an artifact's repository-bound provenance with:

```sh
gh attestation verify ./mindmap_linux_amd64 -R erd0s/mindmap
```

## Windows signing later

The Windows terminal binary is currently unsigned. It can still be checksum-verified, but a new download may prompt Microsoft Defender SmartScreen until it earns reputation.

Before publishing a Windows desktop app, choose a maintained signing route: an organization-validation or extended-validation Authenticode certificate, or a managed service such as Azure Trusted Signing where eligible. Sign the executable and installer with `signtool`, include an RFC 3161 timestamp, verify the signature on a clean Windows VM, and retain the signing evidence with the release. Never store a private signing key directly in the repository or an unprotected workflow secret.
