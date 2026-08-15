#!/bin/sh
set -eu

repository=erd0s/mindmap
environment=release
p12_path=
signing_identity=
apple_id=
team_id=

usage() {
  cat <<'EOF'
Usage: configure_macos_signing.sh --p12 FILE --identity NAME --apple-id EMAIL --team-id ID

Uploads the six macOS signing values to the protected GitHub release environment.
The script prompts privately for the .p12 export password and Apple app-specific
password. It never prints either value or writes it to disk.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --p12)
      [ "$#" -ge 2 ] || { usage >&2; exit 2; }
      p12_path=$2
      shift 2
      ;;
    --identity)
      [ "$#" -ge 2 ] || { usage >&2; exit 2; }
      signing_identity=$2
      shift 2
      ;;
    --apple-id)
      [ "$#" -ge 2 ] || { usage >&2; exit 2; }
      apple_id=$2
      shift 2
      ;;
    --team-id)
      [ "$#" -ge 2 ] || { usage >&2; exit 2; }
      team_id=$2
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

case "$p12_path" in
  \~/*) p12_path=$HOME/${p12_path#\~/} ;;
esac

if [ "$(uname -s)" != Darwin ]; then
  printf '%s\n' 'Run this script on the Mac whose Keychain contains the signing identity.' >&2
  exit 2
fi
for command in gh security base64 stty; do
  command -v "$command" >/dev/null 2>&1 || {
    printf 'Required command not found: %s\n' "$command" >&2
    exit 2
  }
done
[ -r "$p12_path" ] || { printf 'Cannot read .p12 file: %s\n' "$p12_path" >&2; exit 2; }
[ -n "$signing_identity" ] || { printf '%s\n' 'Missing --identity.' >&2; exit 2; }
[ -n "$apple_id" ] || { printf '%s\n' 'Missing --apple-id.' >&2; exit 2; }
[ "${#team_id}" -eq 10 ] || { printf '%s\n' 'The Apple Team ID must be 10 characters.' >&2; exit 2; }
case "$team_id" in
  *[!A-Za-z0-9]*)
    printf '%s\n' 'The Apple Team ID must contain only letters and numbers.' >&2
    exit 2
    ;;
esac
case "$signing_identity" in
  'Developer ID Application: '*) ;;
  *)
    printf '%s\n' 'The signing identity must begin with "Developer ID Application: ".' >&2
    exit 2
    ;;
esac

security find-identity -v -p codesigning | grep -F "\"$signing_identity\"" >/dev/null || {
  printf 'The Keychain does not contain this valid signing identity: %s\n' "$signing_identity" >&2
  exit 2
}
gh auth status --hostname github.com >/dev/null
gh api "repos/$repository/environments/$environment" >/dev/null

read_hidden() {
  prompt=$1
  printf '%s' "$prompt" >/dev/tty
  trap 'stty echo </dev/tty' HUP INT TERM EXIT
  stty -echo </dev/tty
  IFS= read -r hidden_value </dev/tty
  stty echo </dev/tty
  trap - HUP INT TERM EXIT
  printf '\n' >/dev/tty
  [ -n "$hidden_value" ] || { printf '%s\n' 'The value cannot be empty.' >&2; exit 2; }
}

read_hidden '.p12 export password: '
certificate_password=$hidden_value
read_hidden 'Apple app-specific password: '
apple_app_password=$hidden_value
unset hidden_value

base64 -i "$p12_path" | tr -d '\r\n' | gh secret set MACOS_CERTIFICATE --repo "$repository" --env "$environment"
printf '%s' "$certificate_password" | gh secret set MACOS_CERTIFICATE_PASSWORD --repo "$repository" --env "$environment"
printf '%s' "$signing_identity" | gh secret set MACOS_SIGNING_IDENTITY --repo "$repository" --env "$environment"
printf '%s' "$apple_id" | gh secret set APPLE_ID --repo "$repository" --env "$environment"
printf '%s' "$team_id" | gh secret set APPLE_TEAM_ID --repo "$repository" --env "$environment"
printf '%s' "$apple_app_password" | gh secret set APPLE_APP_PASSWORD --repo "$repository" --env "$environment"
unset certificate_password apple_app_password

printf '\nConfigured release environment secrets:\n'
gh secret list --repo "$repository" --env "$environment"
