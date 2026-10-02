#!/data/data/com.termux/files/usr/bin/bash
# One-shot installer: restores full Gitty with Body preview fix
set -e
echo "[*] Downloading base version..."
BASE_URL="https://api.github.com/repos/alipoorkaramali/new-youtube-SoundCloud-downloader/contents/docs/gitty.sh?ref=85b99db864a1a5f521bba051b3e787a464f84a3c"
TMP=$(mktemp)
curl -sL -H "Authorization: token ${GITHUB_TOKEN}" -H "Accept: application/vnd.github.raw" "$BASE_URL" -o "$TMP"
if [[ ! -s "$TMP" ]] || head -1 "$TMP" | grep -q "TEMPORARY\|PLACEHOLDER\|Please wait"; then
  echo "[!] Download failed or got bad file"
  exit 1
fi
echo "[*] Applying Body preview fix..."
python3 - "$TMP" << 'PYEOF'
import sys, base64, pathlib
path = sys.argv[1]
text = pathlib.Path(path).read_text()
old_start = 'printf "${YELLOW}|${NC} ${BOLD}%-*s${NC} ${YELLOW}|${NC}\\n" $((box_w-2)) "Body (preview)"'
end_marker = 'local shortcodes=($(echo "$issue_body"'
i0 = text.find(old_start)
i1 = text.find(end_marker, i0)
if i0 < 0 or i1 < 0:
    print("Could not find body preview section")
    sys.exit(1)
NEW_BLOCK_B64 = "PLACEHOLDER_B64"
new_block = base64.b64decode(NEW_BLOCK_B64).decode()
text = text[:i0] + new_block + text[i1:]
pathlib.Path(path).write_text(text)
print("Patched OK, size", len(text))
PYEOF
echo "[*] Installing..."
cp "$TMP" "$HOME/gitty.sh"
chmod +x "$HOME/gitty.sh"
mkdir -p "$HOME/bin"
cp "$HOME/gitty.sh" "$HOME/bin/gitty"
chmod +x "$HOME/bin/gitty"
hash -r 2>/dev/null || true
cp "$TMP" /sdcard/Download/gitty.sh 2>/dev/null || true
rm -f "$TMP"
echo "[+] Done! Run: gitty"
echo "[+] File also at: $HOME/gitty.sh and $HOME/bin/gitty"
