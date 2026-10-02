#!/data/data/com.termux/files/usr/bin/bash
# Gitty bootstrap - installs full version with Body preview fix
set -e

if [[ -z "${GITHUB_TOKEN:-}" ]]; then
  if [[ -f "$HOME/.github_token" ]]; then
    GITHUB_TOKEN=$(cat "$HOME/.github_token"); export GITHUB_TOKEN
  else
    echo -n "GitHub token: "; read -s GITHUB_TOKEN; echo; export GITHUB_TOKEN
  fi
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd || echo "")"
INSTALLER_URL="https://api.github.com/repos/alipoorkaramali/new-youtube-SoundCloud-downloader/contents/docs/install_full_gitty.sh"

echo "[*] Fetching full installer..."
INST=$(mktemp)
curl -sL -H "Authorization: token $GITHUB_TOKEN" -H "Accept: application/vnd.github.raw" "$INSTALLER_URL" -o "$INST"

if ! grep -q "Body preview fix\|NEW_BLOCK_B64\|Applying Body preview" "$INST" 2>/dev/null; then
  echo "[!] Installer not ready yet. Restoring last good version..."
  curl -sL -H "Authorization: token $GITHUB_TOKEN" -H "Accept: application/vnd.github.raw" \
    "https://api.github.com/repos/alipoorkaramali/new-youtube-SoundCloud-downloader/contents/docs/gitty.sh?ref=85b99db864a1a5f521bba051b3e787a464f84a3c" \
    -o "$HOME/gitty.sh"
  chmod +x "$HOME/gitty.sh"
  mkdir -p "$HOME/bin"
  cp "$HOME/gitty.sh" "$HOME/bin/gitty"
  chmod +x "$HOME/bin/gitty"
  hash -r 2>/dev/null || true
  echo "[+] Restored good version (without latest Body preview fix). Run: gitty"
  rm -f "$INST"
  exec bash "$HOME/gitty.sh"
fi

bash "$INST"
rm -f "$INST"
