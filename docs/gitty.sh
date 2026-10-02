#!/data/data/com.termux/files/usr/bin/bash
# Gitty - GitHub Manager for Termux (TUI) v2.2
# gitty-patch-id: p5-fullbody-order-1to10

DEBUG="${DEBUG:-false}"
set -eo pipefail
if [[ "$DEBUG" == true ]]; then set -x; fi

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

for cmd in curl jq python3; do
    if ! command -v $cmd &> /dev/null; then
        echo -e "${YELLOW}[*] Installing $cmd...${NC}"
        pkg install $cmd -y
    fi
done
if ! command -v base64 &> /dev/null; then pkg install coreutils -y; fi
if ! command -v fribidi &> /dev/null; then pkg install fribidi -y 2>/dev/null || true; fi

if [[ -z "${GITHUB_TOKEN:-}" ]]; then
    if [[ -f "$HOME/.github_token" ]]; then
        GITHUB_TOKEN=$(cat "$HOME/.github_token"); export GITHUB_TOKEN
        echo -e "${GREEN}✅ Token loaded from ~/.github_token${NC}"
    else
        echo -ne "${YELLOW}[?] Enter your GitHub token: ${NC}"
        read -s GITHUB_TOKEN; echo ""
        if [[ -z "$GITHUB_TOKEN" ]]; then echo -e "${RED}❌ Token is required.${NC}"; exit 1; fi
        echo -ne "${YELLOW}Save token to ~/.github_token for future? (y/n): ${NC}"
        read save_choice
        if [[ "$save_choice" == "y" ]]; then
            echo "$GITHUB_TOKEN" > "$HOME/.github_token"; chmod 600 "$HOME/.github_token"
            echo -e "${GREEN}✅ Token saved.${NC}"
        fi
    fi
fi
if ! curl -s -o /dev/null -w "%{http_code}" -H "Authorization: token $GITHUB_TOKEN" https://api.github.com/user | grep -q 200; then
    echo -e "${RED}❌ Invalid token or no internet connection.${NC}"; exit 1
fi

urlencode() { python3 -c "import urllib.parse, sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$1"; }

rtl() {
    local text="$1"
    if [[ "$text" != *[![:ascii:]]* ]]; then printf '%s' "$text"; return; fi
    if command -v fribidi &>/dev/null; then
        printf '%s' "$text" | fribidi --nopad --nobreak 2>/dev/null || printf '%s' "$text"
    else printf '%s' "$text"; fi
}

print_item() {
    local num=$1 type=$2 name=$3 display_name
    display_name=$(rtl "$name")
    if [[ "$type" == "dir" ]]; then
        printf "  ${CYAN}[%2d]${NC} ${BOLD}%s/${NC}\n" "$num" "$display_name"
    else
        printf "  ${YELLOW}[%2d]${NC} %s\n" "$num" "$display_name"
    fi
}

get_repo_selection() {
    local prompt="${1:-Repository (user/repo):}"
    echo -e "${YELLOW}Choose repository:${NC}" >&2
    echo "  1) Enter manually" >&2
    echo "  2) Select from your repositories" >&2
    echo -ne "${YELLOW}> ${NC}" >&2
    read choice
    case $choice in
        1) echo -ne "${YELLOW}${prompt}${NC}" >&2; read repo; echo "$repo" ;;
        2)
            if ! command -v jq &> /dev/null; then
                echo -e "${RED}❌ jq is not installed.${NC}" >&2
                echo -ne "${YELLOW}Enter manually: ${NC}" >&2; read repo; echo "$repo"; return
            fi
            echo -e "${CYAN}Fetching your repositories...${NC}" >&2
            repos_json=$(curl -s -H "Authorization: token $GITHUB_TOKEN" "https://api.github.com/user/repos?per_page=100&sort=updated")
            if [[ -z "$repos_json" ]]; then
                echo -e "${RED}❌ Failed to fetch.${NC}" >&2
                echo -ne "${YELLOW}Enter manually: ${NC}" >&2; read repo; echo "$repo"; return
            fi
            repo_names=()
            while IFS= read -r line; do repo_names+=("$line"); done < <(echo "$repos_json" | jq -r '.[] | .full_name' 2>/dev/null)
            if [[ ${#repo_names[@]} -eq 0 ]]; then
                echo -e "${RED}No repositories found.${NC}" >&2
                echo -ne "${YELLOW}Enter manually: ${NC}" >&2; read repo; echo "$repo"; return
            fi
            echo -e "${CYAN}Your repositories:${NC}" >&2
            for i in "${!repo_names[@]}"; do echo "  $((i+1))) ${repo_names[$i]}" >&2; done
            echo -ne "${YELLOW}Select number (or 0 for manual input): ${NC}" >&2; read num
            if [[ "$num" == "0" ]]; then echo -ne "${YELLOW}${prompt}${NC}" >&2; read repo; echo "$repo"
            elif [[ "$num" =~ ^[0-9]+$ ]] && (( num >= 1 && num <= ${#repo_names[@]} )); then echo "${repo_names[$((num-1))]}"
            else echo -e "${RED}Invalid selection.${NC}" >&2; echo -ne "${YELLOW}Enter manually: ${NC}" >&2; read repo; echo "$repo"; fi
            ;;
        *) echo -e "${RED}Invalid option.${NC}" >&2; echo -ne "${YELLOW}Enter manually: ${NC}" >&2; read repo; echo "$repo" ;;
    esac
}

api_call() {
    local method=$1 url=$2 data=$3
    if [[ -z "$GITHUB_TOKEN" ]]; then echo '{"error": "No GitHub token"}'; return 1; fi
    if [[ -z "$data" ]]; then
        response=$(curl -s -X "$method" -H "Authorization: token $GITHUB_TOKEN" -H "Accept: application/vnd.github.v3+json" "$url")
    else
        response=$(curl -s -X "$method" -H "Authorization: token $GITHUB_TOKEN" -H "Accept: application/vnd.github.v3+json" "$url" -d "$data")
    fi
    echo "$response"
}

api_list() { curl -s -H "Authorization: token $GITHUB_TOKEN" "https://api.github.com/repos/$1/contents/$2"; }
api_get_file() { curl -s -H "Authorization: token $GITHUB_TOKEN" -H "Accept: application/vnd.github.raw" "https://api.github.com/repos/$1/contents/$(urlencode "$2")"; }
api_delete() {
    local encoded_path=$(urlencode "$2")
    curl -s -X DELETE -H "Authorization: token $GITHUB_TOKEN" -H "Accept: application/vnd.github.v3+json" "https://api.github.com/repos/$1/contents/$encoded_path" -d "{\"message\":\"Delete $2\",\"sha\":\"$3\"}" | jq -r '.commit.message // .message // empty'
}

delete_path_recursive() {
    local repo=$1 path=$2 indent="${3:-  }"
    local items=$(api_list "$repo" "$path")
    if echo "$items" | jq -e '.sha' &>/dev/null && ! echo "$items" | jq -e 'type == "array"' &>/dev/null; then
        local file_sha=$(echo "$items" | jq -r '.sha')
        echo -e "${indent}Deleting file: $path"
        api_delete "$repo" "$path" "$file_sha" > /dev/null; return
    fi
    if echo "$items" | jq -e '.message' &>/dev/null; then
        echo -e "${RED}${indent}Cannot list $path: $(echo "$items" | jq -r '.message')${NC}"; return 1
    fi
    local -a child_names child_types child_shas
    child_names=(); child_types=(); child_shas=()
    while IFS=$'\t' read -r ctype cname csha; do
        [[ -z "$cname" ]] && continue
        child_names+=("$cname"); child_types+=("$ctype"); child_shas+=("$csha")
    done < <(echo "$items" | jq -r '.[] | "\(.type)\t\(.name)\t\(.sha)"')
    local i
    for i in "${!child_names[@]}"; do
        if [[ "${child_types[$i]}" == "dir" ]]; then
            local child_path="${path}/${child_names[$i]}"; child_path="${child_path#/}"
            echo -e "${indent}Entering dir: $child_path"
            delete_path_recursive "$repo" "$child_path" "${indent}  "
        fi
    done
    for i in "${!child_names[@]}"; do
        if [[ "${child_types[$i]}" == "file" ]]; then
            local child_path="${path}/${child_names[$i]}"; child_path="${child_path#/}"
            echo -e "${indent}Deleting file: $child_path"
            api_delete "$repo" "$child_path" "${child_shas[$i]}" > /dev/null
        fi
    done
}

api_upload() {
    local repo=$1 local_file=$2 repo_path=$3
    local b64=$(base64 -w0 "$local_file") encoded_path=$(urlencode "$repo_path")
    local existing=$(curl -s -H "Authorization: token $GITHUB_TOKEN" -H "Accept: application/vnd.github.v3+json" "https://api.github.com/repos/$repo/contents/$encoded_path")
    local sha="" msg="Add $repo_path"
    if echo "$existing" | jq -e '.sha' &>/dev/null; then sha=$(echo "$existing" | jq -r '.sha'); msg="Update $repo_path"; fi
    local payload
    if [[ -n "$sha" ]]; then
        payload=$(jq -n --arg message "$msg" --arg content "$b64" --arg sha "$sha" '{message: $message, content: $content, sha: $sha}')
    else
        payload=$(jq -n --arg message "$msg" --arg content "$b64" '{message: $message, content: $content}')
    fi
    echo "$payload" | curl -s -X PUT -H "Authorization: token $GITHUB_TOKEN" -H "Accept: application/vnd.github.v3+json" "https://api.github.com/repos/$repo/contents/$encoded_path" -d @-
}

browse_repo() {
    local repo=$1 current_path=""
    local -a names types shas display_indices
    while true; do
        clear
        echo -e "${CYAN}==============================${NC}"
        echo -e "${CYAN}  Gitty Browser - $repo${NC}"
        echo -e "${CYAN}==============================${NC}"
        echo -e "${YELLOW}Path: /${current_path}${NC}\n"
        local items_json=$(api_list "$repo" "$current_path")
        if echo "$items_json" | jq -e '.message' &>/dev/null; then
            echo -e "${RED}$items_json${NC}"; read -p "Press Enter to go back."; return
        fi
        names=(); types=(); shas=()
        while IFS=$'\t' read -r type name sha; do names+=("$name"); types+=("$type"); shas+=("$sha"); done < <(echo "$items_json" | jq -r '.[] | "\(.type)\t\(.name)\t\(.sha)"')
        display_indices=(); local idx=1
        for i in "${!names[@]}"; do
            if [[ "${types[$i]}" == "dir" ]]; then
                print_item $idx "${types[$i]}" "${names[$i]}"
                display_indices+=("$i")
                idx=$((idx+1))
            fi
        done
        for i in "${!names[@]}"; do
            if [[ "${types[$i]}" == "file" ]]; then
                print_item $idx "${types[$i]}" "${names[$i]}"
                display_indices+=("$i")
                idx=$((idx+1))
            fi
        done
        echo ""
        echo -e "${CYAN}Commands: [number] enter | r<num> read | d<num> download | x<num> delete | b back | q quit${NC}"
        echo -ne "${YELLOW}> ${NC}"; read choice
        case "$choice" in
            [0-9]*)
                local disp_index=$((choice - 1))
                if [[ $disp_index -ge 0 && $disp_index -lt ${#display_indices[@]} ]]; then
                    local item_index=${display_indices[$disp_index]}
                    if [[ "${types[$item_index]}" == "dir" ]]; then current_path="${current_path}/${names[$item_index]}"; current_path="${current_path#/}"
                    else echo -e "${RED}Not a directory.${NC}"; sleep 1; fi
                else echo -e "${RED}Invalid selection.${NC}"; sleep 1; fi
                ;;
            r*)
                local read_num=${choice#r} disp_index=$((read_num - 1))
                if [[ $disp_index -ge 0 && $disp_index -lt ${#display_indices[@]} ]]; then
                    local read_index=${display_indices[$disp_index]}
                    if [[ "${types[$read_index]}" == "file" ]]; then
                        local full_path="${current_path:+$current_path/}${names[$read_index]}"
                        echo -e "${CYAN}--- ${full_path} ---${NC}"
                        if command -v fribidi &>/dev/null; then api_get_file "$repo" "$full_path" | fribidi --nopad 2>/dev/null | less || true
                        else api_get_file "$repo" "$full_path" | less || true; fi
                    else echo -e "${RED}Not a file.${NC}"; sleep 1; fi
                else echo -e "${RED}Invalid file selection.${NC}"; sleep 1; fi
                ;;
            d*)
                local dl_num=${choice#d} disp_index=$((dl_num - 1))
                if [[ $disp_index -ge 0 && $disp_index -lt ${#display_indices[@]} ]]; then
                    local dl_index=${display_indices[$disp_index]}
                    if [[ "${types[$dl_index]}" != "file" ]]; then echo -e "${RED}Not a file.${NC}"; sleep 1; continue; fi
                    local full_path="${current_path:+$current_path/}${names[$dl_index]}" out_name="${names[$dl_index]}"
                    echo -ne "${YELLOW}Save as (default: $out_name): ${NC}"; read out; out=${out:-$HOME/storage/shared/Download/$out_name}
                    mkdir -p "$(dirname "$out")"
                    echo -e "${CYAN}Downloading $full_path ...${NC}"
                    local encoded_path=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$full_path', safe=''))")
                    if curl -L --progress-bar --retry 5 --retry-delay 2 --retry-max-time 60 --continue-at - -H "Authorization: token $GITHUB_TOKEN" -H "Accept: application/vnd.github.raw" "https://api.github.com/repos/${repo}/contents/${encoded_path}" --output "$out"; then
                        echo -e "${GREEN}✅ Saved to $out${NC}"
                    else echo -e "${RED}❌ Download failed.${NC}"; rm -f "$out"; fi
                    sleep 1
                else echo -e "${RED}Invalid file selection.${NC}"; sleep 1; fi
                ;;
            x*)
                local del_num=${choice#x} disp_index=$((del_num - 1))
                if [[ $disp_index -ge 0 && $disp_index -lt ${#display_indices[@]} ]]; then
                    local del_index=${display_indices[$disp_index]}
                    local full_path="${current_path:+$current_path/}${names[$del_index]}"
                    echo -ne "${RED}Delete $full_path? (yes/no): ${NC}"; read confirm
                    if [[ "$confirm" == "yes" ]]; then
                        if [[ "${types[$del_index]}" == "dir" ]]; then
                            echo -e "${YELLOW}Deleting folder recursively...${NC}"
                            delete_path_recursive "$repo" "$full_path"; echo -e "${GREEN}✅ Folder deleted.${NC}"
                        else api_delete "$repo" "$full_path" "${shas[$del_index]}" > /dev/null; echo -e "${GREEN}✅ Deleted.${NC}"; fi
                        sleep 1
                    fi
                else echo -e "${RED}Invalid selection.${NC}"; sleep 1; fi
                ;;
            b|B) if [[ -z "$current_path" ]]; then break; else current_path=$(dirname "$current_path"); [[ "$current_path" == "." ]] && current_path=""; fi ;;
            q) break ;;
            *) echo -e "${RED}Unknown command.${NC}"; sleep 1 ;;
        esac
    done
}

browse_issues() {
    local repo=$1 page=1 per_page=15 state="all"
    while true; do
        clear
        local cols=$(tput cols 2>/dev/null || echo 40); [[ "$cols" -lt 30 ]] && cols=40
        local dsep=$(printf '%*s' "$cols" '' | tr ' ' '=')
        local sep=$(printf '%*s' "$cols" '' | tr ' ' '-')
        echo -e "${CYAN}${dsep}${NC}"
        echo -e "${CYAN}  Issue Browser${NC}"
        echo -e "${CYAN}  Repo: ${BOLD}$repo${NC}"
        echo -e "${CYAN}${sep}${NC}"
        echo -e "  State: ${YELLOW}$state${NC}   Page: ${YELLOW}$page${NC}"
        echo -e "${CYAN}${dsep}${NC}"
        echo ""
        local issues_json=$(curl -s -H "Authorization: token $GITHUB_TOKEN" "https://api.github.com/repos/$repo/issues?state=$state&page=$page&per_page=$per_page&sort=updated&direction=desc")
        if echo "$issues_json" | jq -e '.message' &>/dev/null; then
            echo -e "${RED}$(echo "$issues_json" | jq -r '.message')${NC}"; read -p "Press Enter to go back."; return
        fi
        mapfile -t issue_numbers < <(echo "$issues_json" | jq -r '.[] | .number')
        mapfile -t issue_titles < <(echo "$issues_json" | jq -r '.[] | .title')
        mapfile -t issue_states < <(echo "$issues_json" | jq -r '.[] | .state')
        cols=$(tput cols 2>/dev/null || echo 40); [[ "$cols" -lt 30 ]] && cols=40
        sep=$(printf '%*s' "$cols" '' | tr ' ' '-')
        if [[ ${#issue_numbers[@]} -eq 0 ]]; then echo -e "${YELLOW}No issues found.${NC}"
        else
            echo -e "${CYAN}${sep}${NC}"
            printf "  ${BOLD}%-4s %-6s %s${NC}\n" "#" "State" "Title"
            echo -e "${CYAN}${sep}${NC}"
            for i in "${!issue_numbers[@]}"; do
                local title_display=$(rtl "${issue_titles[$i]}")
                local max_title=$((cols - 14)); [[ $max_title -lt 20 ]] && max_title=20
                if [[ "$title_display" == *"Instagram posts"* ]] || [[ "$title_display" == *"instagram posts"* ]]; then
                    if [[ "$title_display" == *"@"* ]]; then
                        local at_part="${title_display##*@}"; at_part="${at_part%%[[:space:]]*}"
                        title_display="@${at_part}"
                    else title_display="Instagram"; fi
                fi
                if [[ ${#title_display} -gt $max_title ]]; then title_display="${title_display:0:$((max_title-1))}..."; fi
                printf "  ${YELLOW}%-4s${NC} " "${issue_numbers[$i]}"
                if [[ "${issue_states[$i]}" == "open" ]]; then printf "${GREEN}%-6s${NC} " "open"
                else printf "${RED}%-6s${NC} " "closed"; fi
                printf "%s\n" "$title_display"
                echo -e "${CYAN}${sep}${NC}"
            done
        fi
        echo ""
        echo -e "${CYAN}${sep}${NC}"
        echo -e "  ${BOLD}Commands${NC}"
        echo -e "  ${YELLOW}[number]${NC} select  ${YELLOW}s${NC} state  ${YELLOW}n${NC} next  ${YELLOW}p${NC} prev  ${YELLOW}b${NC} back  ${YELLOW}q${NC} quit"
        echo -e "${CYAN}${sep}${NC}"
        echo -ne "${YELLOW}> ${NC}"; read cmd
        case "$cmd" in
            [0-9]*)
                local selected_num=$cmd idx=-1
                for j in "${!issue_numbers[@]}"; do if [[ "${issue_numbers[$j]}" == "$selected_num" ]]; then idx=$j; break; fi; done
                if [[ $idx -eq -1 ]]; then echo -e "${RED}Issue number not found.${NC}"; sleep 1; continue; fi
                local issue_body=$(curl -s -H "Authorization: token $GITHUB_TOKEN" "https://api.github.com/repos/$repo/issues/${issue_numbers[$idx]}" | jq -r '.body // ""')
                clear
                local cols=$(tput cols 2>/dev/null || echo 40); [[ "$cols" -lt 30 ]] && cols=40
                local sep=$(printf '%*s' "$cols" '' | tr ' ' '-')
                local dsep=$(printf '%*s' "$cols" '' | tr ' ' '=')
                local detail_title=$(rtl "${issue_titles[$idx]}")
                echo -e "${CYAN}${dsep}${NC}"
                echo -e "${CYAN}  Issue #${issue_numbers[$idx]}${NC}"
                echo -e "${CYAN}${sep}${NC}"
                echo -e "  ${BOLD}Title${NC}"
                echo -e "  ${detail_title}"
                echo -e "${CYAN}${sep}${NC}"
                if [[ "${issue_states[$idx]}" == "open" ]]; then echo -e "  ${BOLD}State${NC}   ${GREEN}* open${NC}"
                else echo -e "  ${BOLD}State${NC}   ${RED}* closed${NC}"; fi
                echo -e "${CYAN}${dsep}${NC}"
                echo ""

                local box_w=$((cols - 4)); [[ $box_w -lt 20 ]] && box_w=20
                local top_border="+"; local mid_border="+"; local bot_border="+"
                top_border+=$(printf '%*s' "$box_w" '' | tr ' ' '-'); top_border+="+"
                mid_border+=$(printf '%*s' "$box_w" '' | tr ' ' '-'); mid_border+="+"
                bot_border+=$(printf '%*s' "$box_w" '' | tr ' ' '-'); bot_border+="+"

                echo -e "${YELLOW}${top_border}${NC}"
                printf "${YELLOW}|${NC} ${BOLD}%-*s${NC} ${YELLOW}|${NC}\n" $((box_w-2)) "Body (preview · ✓p5)"
                echo -e "${YELLOW}${mid_border}${NC}"
                if [[ -z "$issue_body" || "$issue_body" == "null" ]]; then
                    echo -e "${YELLOW}|${NC} (empty)"
                else
                    local row_count=0
                    local line_w=$((cols - 6)); [[ $line_w -lt 24 ]] && line_w=24
                    # helper: print one Persian/English line readable in Termux
                    _gitty_show() {
                        local s="$1"
                        [[ -z "$s" ]] && return
                        if command -v fribidi &>/dev/null; then
                            s=$(printf '%s' "$s" | fribidi --nopad --nobreak 2>/dev/null || printf '%s' "$s")
                        fi
                        # U+202D LTR override ... U+202C pop — stop Termux re-reversing
                        printf '%b\n' "${YELLOW}|${NC} "$'\u202D'"${s}"$'\u202C'
                    }
                    while IFS= read -r raw_line || [[ -n "$raw_line" ]]; do
                        local trimmed="${raw_line#"${raw_line%%[![:space:]]*}"}"
                        [[ -z "$trimmed" ]] && continue
                        [[ "$trimmed" == *"---"* ]] && continue
                        [[ "$trimmed" == *":--"* || "$trimmed" == *"--:"* ]] && continue
                        [[ "$trimmed" == *"shortcode"* && "$trimmed" == *"caption"* ]] && continue
                        [[ "$trimmed" == *"Updated:"* || "$trimmed" == *"_Updated"* ]] && continue
                        if [[ "$trimmed" == *"Instagram"* || "$trimmed" == *"instagram"* ]]; then
                            if [[ "$trimmed" == *"@"* ]]; then
                                local atp="${trimmed##*@}"; atp="${atp%%[[:space:]]*}"; atp="${atp%%]*}"
                                echo -e "${YELLOW}|${NC} 📷 @${atp}"
                            fi
                            continue
                        fi
                        if [[ "$trimmed" == "|"* ]]; then
                            local clean="$trimmed"
                            clean="${clean#|}"; clean="${clean%|}"
                            IFS='|' read -ra cols_arr <<< "$clean"
                            local num_col="" sc_col="" cap_col="" cidx=0
                            for c in "${cols_arr[@]}"; do
                                c="${c#"${c%%[![:space:]]*}"}"; c="${c%"${c##*[![:space:]]}"}"
                                if [[ $cidx -eq 0 ]]; then num_col="$c"
                                elif [[ $cidx -eq 1 ]]; then sc_col="$c"
                                else
                                    if [[ -n "$cap_col" ]]; then cap_col="$cap_col | $c"; else cap_col="$c"; fi
                                fi
                                cidx=$((cidx+1))
                            done
                            [[ "$num_col" == "#" || "$sc_col" == "shortcode" ]] && continue
                            [[ -z "$num_col" && -z "$sc_col" ]] && continue

                            echo -e "${YELLOW}|${NC} ${BOLD}#${num_col}${NC}  ${GREEN}${sc_col}${NC}"
                            # caption: logical start, up to 2 lines, then fribidi+LTR each line
                            cap_col="${cap_col//$'\n'/ }"
                            local max_total=$((line_w * 2))
                            if [[ ${#cap_col} -gt $max_total ]]; then
                                cap_col="${cap_col:0:$((max_total-1))}…"
                            fi
                            if [[ ${#cap_col} -gt $line_w ]]; then
                                _gitty_show "  ${cap_col:0:$line_w}"
                                _gitty_show "  ${cap_col:$line_w}"
                            else
                                _gitty_show "  ${cap_col}"
                            fi

                            row_count=$((row_count+1))
                            [[ $row_count -ge 10 ]] && break
                        fi
                    done <<< "$issue_body"
                    [[ $row_count -eq 0 ]] && echo -e "${YELLOW}|${NC} (no preview)"
                fi
                echo -e "${YELLOW}${bot_border}${NC}"
                echo ""

                local shortcodes=($(echo "$issue_body" | grep -oE '`([A-Za-z0-9_-]+)`' | sed 's/`//g' | sort -u))
                echo -e "${GREEN}${top_border}${NC}"
                printf "${GREEN}|${NC} ${BOLD}%-*s${NC} ${GREEN}|${NC}\n" $((box_w-2)) "Shortcodes"
                echo -e "${GREEN}${mid_border}${NC}"
                if [[ ${#shortcodes[@]} -gt 0 ]]; then
                    for sc in "${shortcodes[@]}"; do printf "${GREEN}|${NC} ${BOLD}%-*s${NC} ${GREEN}|${NC}\n" $((box_w-2)) "$sc"; done
                else
                    printf "${GREEN}|${NC} ${YELLOW}%-*s${NC} ${GREEN}|${NC}\n" $((box_w-2)) "(none found)"
                fi
                echo -e "${GREEN}${bot_border}${NC}"
                echo ""

                echo -e "${CYAN}${sep}${NC}"
                echo -e "  ${BOLD}Actions${NC}"
                echo -e "  ${YELLOW}1${NC}) Post /download comment"
                echo -e "  ${YELLOW}2${NC}) View full body (scroll)"
                echo -e "  ${YELLOW}3${NC}) Back to list"
                echo -e "${CYAN}${sep}${NC}"
                echo -ne "${YELLOW}> ${NC}"; read opt
                case "$opt" in
                    1)
                        local sc_to_download=""
                        if [[ ${#shortcodes[@]} -gt 0 ]]; then
                            echo -e "${CYAN}Select shortcode number (1-${#shortcodes[@]}) or enter custom:${NC}"
                            for k in "${!shortcodes[@]}"; do echo "  $((k+1))) ${shortcodes[$k]}"; done
                            read -r sc_choice
                            if [[ "$sc_choice" =~ ^[0-9]+$ ]] && [[ $sc_choice -ge 1 ]] && [[ $sc_choice -le ${#shortcodes[@]} ]]; then sc_to_download="${shortcodes[$((sc_choice-1))]}"
                            else sc_to_download="$sc_choice"; fi
                        else echo -ne "${YELLOW}Enter shortcode manually: ${NC}"; read sc_to_download; fi
                        if [[ -n "$sc_to_download" ]]; then
                            local comment_body="/download $sc_to_download"
                            echo -e "${CYAN}Posting comment: $comment_body${NC}"
                            local response=$(api_call "POST" "https://api.github.com/repos/$repo/issues/${issue_numbers[$idx]}/comments" "{\"body\": \"$comment_body\"}")
                            if echo "$response" | jq -e '.id' &>/dev/null; then echo -e "${GREEN}✅ Comment posted. Workflow triggered.${NC}"
                            else echo -e "${RED}❌ Failed: $(echo "$response" | jq -r '.message')${NC}"; fi
                        else echo -e "${RED}No shortcode provided.${NC}"; fi
                        read -p "Press Enter to continue."
                        ;;
                    2)
                        {
                            local fcols=$(tput cols 2>/dev/null || echo 40); [[ $fcols -lt 30 ]] && fcols=40
                            echo -e "${CYAN}+$(printf '%*s' $((fcols-2)) '' | tr ' ' '-')+${NC}"
                            printf "${CYAN}|${NC} ${BOLD}%-*s${NC} ${CYAN}|${NC}\n" $((fcols-4)) "Issue #${issue_numbers[$idx]} - full body"
                            echo -e "${CYAN}+$(printf '%*s' $((fcols-2)) '' | tr ' ' '-')+${NC}"
                            echo ""
                            if [[ -z "$issue_body" || "$issue_body" == "null" ]]; then
                                echo -e "  ${YELLOW}(empty)${NC}"
                            else
                                local in_table=0
                                while IFS= read -r raw_line || [[ -n "$raw_line" ]]; do
                                    local trimmed="${raw_line#"${raw_line%%[![:space:]]*}"}"
                                    if [[ "$trimmed" == "|"* ]]; then
                                        in_table=1
                                        if [[ "$raw_line" == *"---"* ]] || [[ "$raw_line" == *":--"* ]] || [[ "$raw_line" == *"--:"* ]]; then
                                            continue
                                        fi
                                        local clean="${raw_line#"${raw_line%%[![:space:]]*}"}"
                                        clean="${clean%"${clean##*[![:space:]]}"}"
                                        clean="${clean#|}"; clean="${clean%|}"
                                        IFS='|' read -ra cols_arr <<< "$clean"
                                        local num_col="" sc_col="" cap_col="" cidx=0
                                        for c in "${cols_arr[@]}"; do
                                            c="${c#"${c%%[![:space:]]*}"}"; c="${c%"${c##*[![:space:]]}"}"
                                            if [[ $cidx -eq 0 ]]; then num_col="$c"
                                            elif [[ $cidx -eq 1 ]]; then sc_col="$c"
                                            else
                                                if [[ -n "$cap_col" ]]; then cap_col="$cap_col | $c"; else cap_col="$c"; fi
                                            fi
                                            cidx=$((cidx+1))
                                        done
                                        if command -v fribidi &>/dev/null && [[ -n "$cap_col" ]]; then
                                            cap_col=$(printf '%s' "$cap_col" | fribidi --nopad --nobreak 2>/dev/null || printf '%s' "$cap_col")
                                        fi
                                        echo -e "${YELLOW}+---- # ----+${NC}"
                                        echo -e "${YELLOW}|${NC} ${BOLD}${num_col}${NC}"
                                        echo -e "${YELLOW}+-- shortcode --+${NC}"
                                        echo -e "${YELLOW}|${NC} ${GREEN}${sc_col}${NC}"
                                        echo -e "${YELLOW}+-- caption --+${NC}"
                                        local cap="$cap_col" maxc=$((fcols-4)); [[ $maxc -lt 10 ]] && maxc=10
                                        while [[ ${#cap} -gt $maxc ]]; do
                                            echo -e "${YELLOW}|${NC} ${cap:0:$maxc}"
                                            cap="${cap:$maxc}"
                                        done
                                        echo -e "${YELLOW}|${NC} $cap"
                                        echo -e "${YELLOW}+------------+${NC}"
                                        echo ""
                                    else
                                        if [[ $in_table -eq 1 && -z "$raw_line" ]]; then in_table=0; fi
                                        local display_line
                                        if command -v fribidi &>/dev/null; then
                                            display_line=$(printf '%s' "$raw_line" | fribidi --nopad --nobreak 2>/dev/null || printf '%s' "$raw_line")
                                        else
                                            display_line="$raw_line"
                                        fi
                                        echo -e "  $display_line"
                                    fi
                                done <<< "$issue_body"
                            fi
                            echo ""
                            echo -e "${CYAN}+$(printf '%*s' $((fcols-2)) '' | tr ' ' '-')+${NC}"
                            echo -e "${YELLOW}(q to quit)${NC}"
                        } | less -R || true
                        ;;
                    3) continue ;;
                    *) echo -e "${RED}Invalid option.${NC}"; sleep 1 ;;
                esac
                ;;
            s|S) case "$state" in all) state="open" ;; open) state="closed" ;; closed) state="all" ;; esac; page=1 ;;
            n|N) page=$((page + 1)) ;;
            p|P) [[ $page -gt 1 ]] && page=$((page - 1)) ;;
            b|B) break ;;
            q|Q) return ;;
            *) echo -e "${RED}Unknown command.${NC}"; sleep 1 ;;
        esac
    done
}

action_workflows() {
    local repo=$(get_repo_selection "Repository for workflows (user/repo):")
    if [[ -z "$repo" ]]; then echo -e "${RED}Repo required.${NC}"; return; fi
    while true; do
        clear
        echo -e "${CYAN}==============================${NC}"
        echo -e "${CYAN}  Actions - $repo${NC}"
        echo -e "${CYAN}==============================${NC}"
        echo ""
        echo "  1) List workflows"
        echo "  2) Trigger workflow dispatch (smart)"
        echo "  3) List runs for a workflow"
        echo "  4) View run details"
        echo "  5) Download run logs"
        echo "  6) Cancel a run"
        echo "  7) Rerun a run"
        echo "  8) Enable/disable workflow"
        echo "  9) Back"
        echo ""
        echo -ne "${YELLOW}> ${NC}"; read act_choice
        case "$act_choice" in
            1) echo -e "${CYAN}Workflows:${NC}"; curl -s -H "Authorization: token $GITHUB_TOKEN" "https://api.github.com/repos/$repo/actions/workflows" | jq -r '.workflows[] | "  \(.id)\t\(.name)\t(\(.state))"'; read -p "Press Enter to continue." ;;
            2)
                local wf_list=$(api_call "GET" "https://api.github.com/repos/$repo/actions/workflows" "")
                echo -e "${CYAN}Available workflows:${NC}"
                mapfile -t wf_ids < <(echo "$wf_list" | jq -r '.workflows[] | .id')
                mapfile -t wf_names < <(echo "$wf_list" | jq -r '.workflows[] | .name')
                mapfile -t wf_paths < <(echo "$wf_list" | jq -r '.workflows[] | .path')
                if [[ ${#wf_ids[@]} -eq 0 ]]; then echo -e "${RED}No workflows found.${NC}"; sleep 2; continue; fi
                for i in "${!wf_ids[@]}"; do echo "  $((i+1))) ${wf_names[$i]} (${wf_paths[$i]##*/})"; done
                echo -ne "${YELLOW}Select workflow number: ${NC}"; read wf_num
                if [[ ! "$wf_num" =~ ^[0-9]+$ ]] || [[ $wf_num -lt 1 ]] || [[ $wf_num -gt ${#wf_ids[@]} ]]; then echo -e "${RED}Invalid selection.${NC}"; sleep 2; continue; fi
                local wf_id="${wf_ids[$((wf_num-1))]}" wf_name="${wf_names[$((wf_num-1))]}"
                echo -e "${GREEN}Selected: $wf_name${NC}"
                local default_branch=$(curl -s -H "Authorization: token $GITHUB_TOKEN" "https://api.github.com/repos/$repo" | jq -r '.default_branch')
                echo -ne "${YELLOW}Branch [$default_branch]: ${NC}"; read branch; branch=${branch:-$default_branch}
                local input_json="{}"
                case "$wf_name" in
                    *"Add Watch Item"*| *"add-item"*)
                        echo -ne "Platform (youtube/soundcloud_playlist) [youtube]: "; read platform; platform=${platform:-youtube}
                        echo -ne "Channel ID / playlist URL: "; read channel_id
                        echo -ne "Title keyword: "; read title_keyword
                        echo -ne "Start time (HH:MM) [19:00]: "; read start_time; start_time=${start_time:-19:00}
                        echo -ne "Check every minutes [60]: "; read interval; interval=${interval:-60}
                        echo -ne "Max attempts per day [5]: "; read max_attempts; max_attempts=${max_attempts:-5}
                        input_json=$(jq -n --arg platform "$platform" --arg channel_id "$channel_id" --arg title_keyword "$title_keyword" --arg start_time_iran "$start_time" --argjson check_every_minutes "$interval" --argjson max_attempts "$max_attempts" '{platform: $platform, channel_id: $channel_id, title_keyword: $title_keyword, start_time_iran: $start_time_iran, check_every_minutes: $check_every_minutes, max_attempts: $max_attempts}')
                        ;;
                    *"Multi-Platform Downloader-auto"*| *"NEW2-auto"*)
                        echo -ne "Platform (youtube/soundcloud): "; read platform; echo -ne "URL: "; read url
                        echo -ne "Folder [downloads]: "; read folder; folder=${folder:-downloads}
                        input_json=$(jq -n --arg platform "$platform" --arg url "$url" --arg format "audio" --arg folder "$folder" '{platform: $platform, url: $url, format: $format, folder: $folder}')
                        ;;
                    *"NEW3-costume-Multi-Platform"*| *"costume"*)
                        echo -ne "Platform (youtube/soundcloud): "; read platform; echo -ne "URL: "; read url
                        echo -ne "Format (video/audio) [video]: "; read format; format=${format:-video}
                        echo -ne "Folder [downloads]: "; read folder; folder=${folder:-downloads}
                        input_json=$(jq -n --arg platform "$platform" --arg url "$url" --arg format "$format" --arg folder "$folder" '{platform: $platform, url: $url, format: $format, folder: $folder}')
                        ;;
                    *"Check RSS Log"*| *"check_log"*) input_json="{}" ;;
                    *"Full Diagnostic"*| *"debug_scan"*)
                        echo -ne "YouTube channel ID [UCHZk9MrT3DGWmVqdsj5y0EA]: "; read yt_id; yt_id=${yt_id:-UCHZk9MrT3DGWmVqdsj5y0EA}
                        echo -ne "SoundCloud URL [https://soundcloud.com/iranintl]: "; read sc_url; sc_url=${sc_url:-https://soundcloud.com/iranintl}
                        input_json=$(jq -n --arg youtube_channel_id "$yt_id" --arg soundcloud_url "$sc_url" '{youtube_channel_id: $youtube_channel_id, soundcloud_url: $soundcloud_url}')
                        ;;
                    *"YouTube Multi-Watcher"*| *"scan1"*) input_json="{}" ;;
                    *"instagram-fetcher"*| *"Instagram"*)
                        echo -ne "Username (without @): "; read username
                        if [[ -z "$username" ]]; then echo -e "${RED}Username required.${NC}"; sleep 2; continue; fi
                        echo -ne "Post count [5,10,15,20] (default 5): "; read post_count; post_count=${post_count:-5}
                        if [[ ! "$post_count" =~ ^(5|10|15|20)$ ]]; then post_count=5; fi
                        input_json=$(jq -n --arg username "$username" --arg post_count "$post_count" '{username: $username, post_count: $post_count}')
                        ;;
                    *"Cleanup old audio files"*| *"cleanup_audio"*)
                        echo -ne "Dry run (true/false) [false]: "; read dry_run; dry_run=${dry_run:-false}
                        echo -ne "Max age in hours [12]: "; read max_age_hours; max_age_hours=${max_age_hours:-12}
                        input_json=$(jq -n --arg dry_run "$dry_run" --arg max_age_hours "$max_age_hours" '{dry_run: $dry_run, max_age_hours: $max_age_hours}')
                        ;;
                    *)
                        echo -e "${YELLOW}Unknown workflow. Enter inputs as key=value comma separated (or empty):${NC}"
                        read inputs
                        if [[ -n "$inputs" ]]; then
                            input_json=$(echo "$inputs" | tr ',' '\n' | while IFS='=' read k v; do echo "\"$k\": \"$v\""; done | paste -sd, | jq -c '{ inputs: . }')
                            input_json=$(echo "$input_json" | jq '.inputs')
                        else input_json="{}"; fi
                        ;;
                esac
                local payload=$(jq -n --arg ref "$branch" --argjson inputs "$input_json" '{ref: $ref, inputs: $inputs}')
                echo -e "${CYAN}Sending dispatch...${NC}"
                local response=$(curl -s -X POST -H "Authorization: token $GITHUB_TOKEN" -H "Accept: application/vnd.github.v3+json" "https://api.github.com/repos/$repo/actions/workflows/$wf_id/dispatches" -d "$payload")
                if [[ -z "$response" ]]; then echo -e "${GREEN}✅ Dispatch triggered.${NC}"; else echo -e "${RED}Error: $response${NC}"; fi
                read -p "Press Enter to continue."
                ;;
            3) echo -ne "${YELLOW}Workflow ID: ${NC}"; read wf_id; echo -e "${CYAN}Recent runs:${NC}"; curl -s -H "Authorization: token $GITHUB_TOKEN" "https://api.github.com/repos/$repo/actions/workflows/$wf_id/runs" | jq -r '.workflow_runs[] | "  \(.id)\t\(.status)\t\(.conclusion)\t\(.created_at)"'; read -p "Press Enter to continue." ;;
            4) echo -ne "${YELLOW}Run ID: ${NC}"; read run_id; echo -e "${CYAN}Run details:${NC}"; curl -s -H "Authorization: token $GITHUB_TOKEN" "https://api.github.com/repos/$repo/actions/runs/$run_id" | jq '{status: .status, conclusion: .conclusion, created_at: .created_at, html_url: .html_url, head_branch: .head_branch}'; read -p "Press Enter to continue." ;;
            5) echo -ne "${YELLOW}Run ID: ${NC}"; read run_id; echo -ne "${YELLOW}Save logs as (default: logs-${run_id}.zip): ${NC}"; read logfile; logfile=${logfile:-"logs-${run_id}.zip"}; echo -e "${CYAN}Downloading logs...${NC}"; curl -L -H "Authorization: token $GITHUB_TOKEN" "https://api.github.com/repos/$repo/actions/runs/$run_id/logs" --output "$logfile"; echo -e "${GREEN}✅ Logs saved to $logfile${NC}"; sleep 1 ;;
            6) echo -ne "${YELLOW}Run ID to cancel: ${NC}"; read run_id; curl -s -X POST -H "Authorization: token $GITHUB_TOKEN" "https://api.github.com/repos/$repo/actions/runs/$run_id/cancel" | jq -r '.message'; read -p "Press Enter to continue." ;;
            7) echo -ne "${YELLOW}Run ID to rerun: ${NC}"; read run_id; curl -s -X POST -H "Authorization: token $GITHUB_TOKEN" "https://api.github.com/repos/$repo/actions/runs/$run_id/rerun" | jq -r '.message'; read -p "Press Enter to continue." ;;
            8)
                local wf_list=$(api_call "GET" "https://api.github.com/repos/$repo/actions/workflows" "")
                mapfile -t wf_ids < <(echo "$wf_list" | jq -r '.workflows[] | .id')
                mapfile -t wf_names < <(echo "$wf_list" | jq -r '.workflows[] | .name')
                mapfile -t wf_states < <(echo "$wf_list" | jq -r '.workflows[] | .state')
                if [[ ${#wf_ids[@]} -eq 0 ]]; then echo -e "${RED}No workflows found.${NC}"; sleep 2; continue; fi
                echo -e "${CYAN}Workflows:${NC}"
                for i in "${!wf_ids[@]}"; do
                    local state_icon=""; if [[ "${wf_states[$i]}" == "active" ]]; then state_icon="${GREEN}*${NC}"; else state_icon="${RED}o${NC}"; fi
                    echo "  $((i+1))) $state_icon ${wf_names[$i]} (${wf_states[$i]})"
                done
                echo -ne "${YELLOW}Select workflow number: ${NC}"; read wf_num
                if [[ ! "$wf_num" =~ ^[0-9]+$ ]] || [[ $wf_num -lt 1 ]] || [[ $wf_num -gt ${#wf_ids[@]} ]]; then echo -e "${RED}Invalid selection.${NC}"; sleep 2; continue; fi
                local idx=$((wf_num-1)) wf_id="${wf_ids[$idx]}" wf_name="${wf_names[$idx]}" current_state="${wf_states[$idx]}"
                echo -e "${CYAN}Selected: $wf_name (current state: $current_state)${NC}"
                if [[ "$current_state" == "active" ]]; then
                    echo -ne "${YELLOW}Disable this workflow? (y/n): ${NC}"; read confirm
                    if [[ "$confirm" == "y" || "$confirm" == "yes" ]]; then
                        set +e; local response=$(api_call "POST" "https://api.github.com/repos/$repo/actions/workflows/$wf_id/disable" ""); local exit_code=$?; set -e
                        if [[ $exit_code -ne 0 ]]; then echo -e "${RED}❌ Error: $response${NC}"
                        elif echo "$response" | jq -e '.error' &>/dev/null; then echo -e "${RED}❌ Error: $(echo "$response" | jq -r '.error')${NC}"
                        else echo -e "${GREEN}✅ Workflow disabled.${NC}"; fi
                    else echo -e "${YELLOW}No change.${NC}"; fi
                else
                    echo -ne "${YELLOW}Enable this workflow? (y/n): ${NC}"; read confirm
                    if [[ "$confirm" == "y" || "$confirm" == "yes" ]]; then
                        set +e; local response=$(api_call "PUT" "https://api.github.com/repos/$repo/actions/workflows/$wf_id/enable" ""); local exit_code=$?; set -e
                        if [[ $exit_code -ne 0 ]]; then echo -e "${RED}❌ Error: $response${NC}"
                        elif echo "$response" | jq -e '.error' &>/dev/null; then echo -e "${RED}❌ Error: $(echo "$response" | jq -r '.error')${NC}"
                        else echo -e "${GREEN}✅ Workflow enabled.${NC}"; fi
                    else echo -e "${YELLOW}No change.${NC}"; fi
                fi
                read -p "Press Enter to continue."
                ;;
            9) break ;;
            *) echo -e "${RED}Invalid option.${NC}"; sleep 1 ;;
        esac
    done
}

action_create_repo() {
    echo -e "${YELLOW}Source type: (L)ocal folder or (R)emote GitHub repo? [L/R]:${NC}"
    read -r src_type; src_type=${src_type:-L}; src_type=$(echo "$src_type" | tr '[:lower:]' '[:upper:]')
    if [[ "$src_type" == "L" ]]; then
        echo -e "${YELLOW}Path to source folder (Enter = current):${NC}"
        read -r src_path; src_path="${src_path/#\~/$HOME}"; src_path=${src_path:-$(pwd)}
        if [[ ! -d "$src_path" ]]; then echo -e "${RED}❌ Directory not found.${NC}"; return; fi
        cd "$src_path"; echo -e "${GREEN}Using source: $(pwd)${NC}"
        rm -rf audio_downloads downloads 2>/dev/null
        find . -type f \( -name "*.m4a" -o -name "*.mp3" -o -name "*.mp4" \) -delete 2>/dev/null
    else
        local src_repo=$(get_repo_selection "Source repository (user/repo):")
        echo -e "${YELLOW}Branch [main]:${NC}"; read -r branch; branch=${branch:-main}
        echo -e "${YELLOW}Use ghproxy.com? [Y/n] (recommended):${NC}"; read -r use_proxy; use_proxy=${use_proxy:-y}
        local temp_dir=$(mktemp -d "$HOME/fresh-repo-XXXXXX")
        local zip_url="https://github.com/${src_repo}/archive/refs/heads/${branch}.zip"
        [[ "$use_proxy" =~ ^[Yy] ]] && zip_url="https://ghproxy.com/${zip_url}"
        local zip_file="$temp_dir/repo.zip"
        echo -e "${CYAN}[*] Downloading archive...${NC}"
        if command -v wget &>/dev/null; then wget --show-progress -O "$zip_file" "$zip_url"; else curl -L -# -o "$zip_file" "$zip_url"; fi
        if [[ ! -s "$zip_file" ]]; then echo -e "${RED}❌ Download failed.${NC}"; rm -rf "$temp_dir"; return; fi
        echo -e "${CYAN}[*] Extracting...${NC}"
        unzip -q "$zip_file" -d "$temp_dir"
        local extracted_dir=$(find "$temp_dir" -maxdepth 1 -type d ! -name ".*" ! -name "$(basename "$temp_dir")" | head -1)
        cd "$extracted_dir"
        rm -rf audio_downloads downloads 2>/dev/null
        find . -type f \( -name "*.m4a" -o -name "*.mp3" -o -name "*.mp4" \) -delete 2>/dev/null
    fi
    echo ""
    echo -e "${YELLOW}New repository name:${NC}"; read -r dest_repo
    dest_repo=$(echo "$dest_repo" | tr ' ' '-' | tr -dc '[:alnum:]_.-')
    echo -e "${YELLOW}Public or private? [public/private]:${NC}"; read -r visibility; visibility=${visibility:-public}
    echo -e "${CYAN}[*] Creating remote repo '${dest_repo}'...${NC}"
    curl -s -X POST -H "Authorization: token $GITHUB_TOKEN" -H "Accept: application/vnd.github.v3+json" https://api.github.com/user/repos -d "{\"name\":\"${dest_repo}\", \"private\":$([[ "$visibility" == "private" ]] && echo true || echo false)}" > /dev/null
    echo -e "${CYAN}[*] Uploading files...${NC}"
    find . -type f -not -path './.git/*' | while read -r file; do
        local repo_path="${file#./}"
        echo -ne "  Uploading: $repo_path ... "
        api_upload "$GITHUB_USER/$dest_repo" "$file" "$repo_path" > /dev/null && echo -e "${GREEN}OK${NC}" || echo -e "${RED}FAIL${NC}"
    done
    echo -e "${GREEN}✅ Repository created: https://github.com/$GITHUB_USER/$dest_repo${NC}"
    if [[ "$src_type" == "R" ]]; then rm -rf "$temp_dir"; fi
}

action_upload_files() {
    local target_repo=$(get_repo_selection "Target repository (user/repo):")
    echo -e "${YELLOW}Local file or folder path:${NC}"; read -r local_path
    local_path="${local_path/#\~/$HOME}"
    if [[ ! -e "$local_path" ]]; then echo -e "${RED}❌ Not found.${NC}"; return; fi
    echo -e "${YELLOW}Destination path in repo (e.g., data/ or empty for root):${NC}"; read -r dest_path
    dest_path="${dest_path%/}"; [[ -n "$dest_path" ]] && dest_path="${dest_path}/"
    upload_single() {
        local file=$1 dest=$2 fname=$(basename "$file") repo_path="${dest}${fname}"
        echo -ne "  Uploading: $repo_path ... "
        api_upload "$target_repo" "$file" "$repo_path" > /dev/null && echo -e "${GREEN}OK${NC}" || echo -e "${RED}FAIL${NC}"
    }
    if [[ -f "$local_path" ]]; then upload_single "$local_path" "$dest_path"
    elif [[ -d "$local_path" ]]; then
        cd "$local_path"
        find . -type f | while read -r file; do
            local rel="${file#./}" subdest="$dest_path$(dirname "$rel")/"
            [[ "$subdest" == "./" ]] && subdest="$dest_path"
            upload_single "$(pwd)/$rel" "$subdest"
        done
    fi
    echo -e "${GREEN}✅ Upload complete.${NC}"
}

action_update_gitty() {
    local repo="alipoorkaramali/new-youtube-SoundCloud-downloader"
    local remote_path="docs/gitty.sh"
    local target="${HOME}/gitty.sh"
    local download_dir="$HOME/storage/shared/Download"
    [[ ! -d "$download_dir" ]] && download_dir="/sdcard/Download"
    echo -e "${CYAN}==============================${NC}"
    echo -e "${CYAN}  Update Gitty to latest${NC}"
    echo -e "${CYAN}==============================${NC}"
    echo ""
    echo -e "Target file: ${BOLD}$target${NC}"
    echo -e "Source:      ${BOLD}$repo/$remote_path${NC}"
    echo ""
    echo -ne "${YELLOW}Download and replace $target with latest version? (yes/no): ${NC}"
    read confirm
    if [[ "$confirm" != "yes" ]]; then echo -e "${YELLOW}Cancelled.${NC}"; sleep 1; return; fi
    echo -e "${CYAN}[*] Fetching latest version...${NC}"
    local tmpfile=$(mktemp "$HOME/gitty-update-XXXXXX")
    if curl -s -L -H "Authorization: token $GITHUB_TOKEN" -H "Accept: application/vnd.github.raw" "https://api.github.com/repos/${repo}/contents/${remote_path}" --output "$tmpfile"; then
        if [[ ! -s "$tmpfile" ]]; then echo -e "${RED}❌ Downloaded file is empty. Aborting.${NC}"; rm -f "$tmpfile"; sleep 2; return; fi
        if ! head -1 "$tmpfile" | grep -q "#!/" ; then
            echo -e "${RED}❌ Downloaded content does not look like a script. Aborting.${NC}"
            rm -f "$tmpfile"; sleep 2; return
        fi
        if [[ -f "$target" ]]; then
            cp "$target" "${target}.bak.$(date +%Y%m%d_%H%M%S)"
            echo -e "${GREEN}✅ Backup saved: ${target}.bak.*${NC}"
        fi
        cp "$tmpfile" "$target"; chmod +x "$target"
        echo -e "${GREEN}✅ Updated: $target${NC}"
        mkdir -p "$HOME/bin"
        cp "$tmpfile" "$HOME/bin/gitty"; chmod +x "$HOME/bin/gitty"
        echo -e "${GREEN}✅ Updated: $HOME/bin/gitty${NC}"
        hash -r 2>/dev/null || true
        echo -e "${GREEN}✅ Bash hash cache cleared${NC}"
        if [[ -d "$download_dir" ]]; then
            echo -e "${CYAN}[*] Cleaning old gitty copies in Download...${NC}"
            find "$download_dir" -maxdepth 1 -type f \( -name "gitty.sh" -o -name "gitty-fixed.sh" -o -name "gitty*.sh" -o -name "gitty*.SH" \) -print -delete 2>/dev/null || true
            cp "$tmpfile" "$download_dir/gitty.sh"
            echo -e "${GREEN}✅ Latest also saved to: $download_dir/gitty.sh${NC}"
        fi
        rm -f "$tmpfile"
        echo ""
        echo -e "${GREEN}✅ Gitty updated successfully!${NC}"
        echo -e "${YELLOW}You can now run:  gitty${NC}"
        echo ""
        read -p "Press Enter to continue."
    else
        echo -e "${RED}❌ Failed to download. Check internet or token.${NC}"
        rm -f "$tmpfile"; sleep 2
    fi
}

GITHUB_USER=$(curl -s -H "Authorization: token $GITHUB_TOKEN" https://api.github.com/user | jq -r '.login')

while true; do
    clear
    echo -e "${CYAN}==============================${NC}"
    echo -e "${CYAN}  Gitty - GitHub Manager v2.2${NC}"
    echo -e "${CYAN}==============================${NC}"
    echo -e "${GREEN}Logged in as: ${BOLD}$GITHUB_USER${NC}\n"
    echo "  1) Browse repository"
    echo "  2) Browse issues (open/closed)"
    echo "  3) Create new repository"
    echo "  4) Upload files to existing repository"
    echo "  5) Actions (Workflows)"
    echo "  6) Update Gitty to latest"
    echo "  7) Exit"
    echo ""
    echo -ne "${YELLOW}> ${NC}"
    read -r main_choice
    case "$main_choice" in
        1) repo=$(get_repo_selection "Repository to browse (user/repo):"); browse_repo "$repo" ;;
        2) repo=$(get_repo_selection "Repository for issues (user/repo):"); if [[ -z "$repo" ]]; then echo -e "${RED}Repo required.${NC}"; else browse_issues "$repo"; fi ;;
        3) action_create_repo ;;
        4) action_upload_files ;;
        5) action_workflows ;;
        6) action_update_gitty ;;
        7) echo -e "${GREEN}Bye!${NC}"; exit 0 ;;
        *) echo -e "${RED}Invalid option.${NC}"; sleep 1 ;;
    esac
done
