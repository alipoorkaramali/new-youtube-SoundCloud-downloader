#!/data/data/com.termux/files/usr/bin/bash
# Install full Gitty with Body preview fix
set -e
echo "[*] Downloading base..."
BASE_URL="https://api.github.com/repos/alipoorkaramali/new-youtube-SoundCloud-downloader/contents/docs/gitty.sh?ref=85b99db864a1a5f521bba051b3e787a464f84a3c"
PATCH_URL="https://api.github.com/repos/alipoorkaramali/new-youtube-SoundCloud-downloader/contents/docs/patches/body_preview.txt"
TMP=$(mktemp)
PATCH=$(mktemp)
curl -sL -H "Authorization: token $GITHUB_TOKEN" -H "Accept: application/vnd.github.raw" "$BASE_URL" -o "$TMP"
curl -sL -H "Authorization: token $GITHUB_TOKEN" -H "Accept: application/vnd.github.raw" "$PATCH_URL" -o "$PATCH"
if [[ ! -s "$TMP" || ! -s "$PATCH" ]]; then echo "[!] Download failed"; exit 1; fi
echo "[*] Applying Body preview fix..."
python3 - "$TMP" "$PATCH" << 'PY'
import sys, pathlib
base = pathlib.Path(sys.argv[1]).read_text()
patch = pathlib.Path(sys.argv[2]).read_text()
old_start = 'printf "${YELLOW}|${NC} ${BOLD}%-*s${NC} ${YELLOW}|${NC}\\n" $((box_w-2)) "Body (preview)"'
end_marker = 'local shortcodes=($(echo "$issue_body"'
i0 = base.find(old_start)
i1 = base.find(end_marker, i0)
if i0 < 0 or i1 < 0:
    print('section not found', i0, i1); sys.exit(1)
pathlib.Path(sys.argv[1]).write_text(base[:i0] + patch + base[i1:])
print('Patched OK', len(base[:i0] + patch + base[i1:]))
PY
cp "$TMP" "$HOME/gitty.sh"
chmod +x "$HOME/gitty.sh"
mkdir -p "$HOME/bin"
cp "$HOME/gitty.sh" "$HOME/bin/gitty"
chmod +x "$HOME/bin/gitty"
hash -r 2>/dev/null || true
cp "$TMP" /sdcard/Download/gitty.sh 2>/dev/null || true
rm -f "$TMP" "$PATCH"
echo "[+] Done! Run: gitty"
