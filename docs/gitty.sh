#!/data/data/com.termux/files/usr/bin/bash
# ═══════════════════════════════════════════════════════════════════
#  Gitty - GitHub Manager for Termux (TUI) v2.1.1
# ═══════════════════════════════════════════════════════════════════

# ─── Debug mode ────────────────────────────────
DEBUG="${DEBUG:-false}"   # با true اجرا کنید: DEBUG=true bash script.sh

set -eo pipefail
if [[ "$DEBUG" == true ]]; then
    set -x
fi

# ─── Colors ────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ─── Check & install required tools ───────────
for cmd in curl jq python3; do
    if ! command -v $cmd &> /dev/null; then
        echo -e "${YELLOW}[*] Installing $cmd...${NC}"
        pkg install $cmd -y
    fi
done

# base64 is part of coreutils; ensure it exists
if ! command -v base64 &> /dev/null; then
    echo -e "${YELLOW}[*] Installing coreutils (provides base64)...${NC}"
    pkg install coreutils -y
fi


# ─── Token management ─────────────────────────
if [[ -z "${GITHUB_TOKEN:-}" ]]; then
    if [[ -f "$HOME/.github_token" ]]; then
        GITHUB_TOKEN=$(cat "$HOME/.github_token")
        export GITHUB_TOKEN
        echo -e "${GREEN}✅ Token loaded from ~/.github_token${NC}"
    else
        echo -ne "${YELLOW}[?] Enter your GitHub token: ${NC}"
        read -s GITHUB_TOKEN
        echo ""
        if [[ -z "$GITHUB_TOKEN" ]]; then
            echo -e "${RED}❌ Token is required.${NC}"
            exit 1
        fi
        # optionally save it for next time
        echo -ne "${YELLOW}Save token to ~/.github_token for future? (y/n): ${NC}"
        read save_choice
        if [[ "$save_choice" == "y" ]]; then
            echo "$GITHUB_TOKEN" > "$HOME/.github_token"
            chmod 600 "$HOME/.github_token"
            echo -e "${GREEN}✅ Token saved.${NC}"
        fi
    fi
fi

# Verify token once (silent)
if ! curl -s -o /dev/null -w "%{http_code}" -H "Authorization: token $GITHUB_TOKEN" https://api.github.com/user | grep -q 200; then
    echo -e "${RED}❌ Invalid token or no internet connection.${NC}"
    exit 1
fi

# ─── Helper functions ─────────────────────────
urlencode() {
    python3 -c "import urllib.parse, sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$1"
}

print_item() {
    local num=$1 type=$2 name=$3
    if [[ "$type" == "dir" ]]; then
        printf "  ${CYAN}[%2d]${NC} ${BOLD}%s/${NC}\n" "$num" "$name"
    else
        printf "  ${YELLOW}[%2d]${NC} %s\n" "$num" "$name"
    fi
}
