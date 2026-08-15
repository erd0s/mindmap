# Releasing Mindmap

The first public release publishes a signed universal macOS desktop app, cross-platform terminal binaries, two agent-plugin packages, and SHA-256 checksums. Windows and Linux desktop packages are intentionally deferred.

## Apple signing setup

Create a **Developer ID Application** certificate in the Apple Developer account, install it in Keychain Access, and export the certificate plus private key as a password-protected `.p12` file. Create an app-specific password for the Apple ID used by the workflow.

Create a GitHub Actions environment named `release`, then add these values as environment secrets rather than repository secrets:

| Secret | Value |
|---|---|
| `MACOS_CERTIFICATE` | Base64-encoded `.p12` contents |
| `MACOS_CERTIFICATE_PASSWORD` | Export password for the `.p12` |
| `MACOS_SIGNING_IDENTITY` | Full Developer ID Application identity shown by `security find-identity -v -p codesigning` |
| `APPLE_ID` | Apple ID used for notarization |
| `APPLE_TEAM_ID` | Ten-character Apple Developer team ID |
| `APPLE_APP_PASSWORD` | App-specific password |

Configure the `release` environment with a required reviewer and restrict deployments to tags matching `v*`. Before granting anyone else write access, create a repository ruleset that protects matching tags from unauthorized creation, update, or deletion. These GitHub settings are manual; the workflow cannot create or verify them. Together, the environment and tag rules stop an unapproved tag workflow from reading the signing credentials.

Encode the certificate on macOS with:

```sh
base64 -i DeveloperIDApplication.p12 | pbcopy
```

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

Review `CHANGELOG.md`, confirm that the package version and plugin manifests agree, and replace both screenshot placeholders in `docs/images/`.

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
