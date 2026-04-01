#!/usr/bin/env bash

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "ERROR: setup_common.sh must be sourced, not executed directly." >&2
    exit 1
fi

log_info() {
    printf '%s\n' "$*"
}

log_warn() {
    printf 'WARNING: %s\n' "$*" >&2
}

log_error() {
    printf 'ERROR: %s\n' "$*" >&2
}

die() {
    log_error "$*"
    exit 1
}

run_privileged() {
    if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
        "$@"
        return
    fi

    if command -v sudo >/dev/null 2>&1; then
        sudo "$@"
        return
    fi

    die "Administrative privileges are required to install Python packages: $*"
}

python_meets_requirement() {
    local python_cmd="$1"
    "$python_cmd" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1
}

find_python_command() {
    local candidate

    for candidate in python3.13 python3.12 python3.11 python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 && python_meets_requirement "$candidate"; then
            command -v "$candidate"
            return 0
        fi
    done

    return 1
}

python_supports_venv() {
    local python_cmd="$1"
    "$python_cmd" -m venv --help >/dev/null 2>&1
}

detect_package_manager() {
    local manager

    for manager in apt-get dnf yum pacman zypper brew; do
        if command -v "$manager" >/dev/null 2>&1; then
            printf '%s\n' "$manager"
            return 0
        fi
    done

    return 1
}

install_python_runtime() {
    local manager

    manager="$(detect_package_manager || true)"
    [[ -n "$manager" ]] || die "Python 3.11+ is not installed and no supported package manager was found."

    log_info "Python 3.11+ not found. Attempting installation with $manager..."

    case "$manager" in
        apt-get)
            run_privileged apt-get update
            run_privileged apt-get install -y python3 python3-venv python3-pip
            ;;
        dnf)
            run_privileged dnf install -y python3 python3-pip
            ;;
        yum)
            run_privileged yum install -y python3 python3-pip
            ;;
        pacman)
            run_privileged pacman -Sy --noconfirm python python-pip
            ;;
        zypper)
            run_privileged zypper --non-interactive install python3 python3-pip
            ;;
        brew)
            brew install python
            ;;
        *)
            die "Unsupported package manager: $manager"
            ;;
    esac
}

ensure_python_runtime() {
    local python_cmd

    python_cmd="$(find_python_command || true)"
    if [[ -z "$python_cmd" ]]; then
        install_python_runtime
        python_cmd="$(find_python_command || true)"
    fi

    [[ -n "$python_cmd" ]] || die "Unable to find Python 3.11+ after installation attempt."

    if ! python_supports_venv "$python_cmd"; then
        install_python_runtime
        python_cmd="$(find_python_command || true)"
    fi

    [[ -n "$python_cmd" ]] || die "Unable to find a usable Python interpreter."
    python_supports_venv "$python_cmd" || die "Python was found, but the venv module is unavailable."

    printf '%s\n' "$python_cmd"
}

ensure_repo_venv() {
    local repo_root="$1"
    local python_cmd="$2"
    local venv_dir="$repo_root/.venv"

    if [[ -d "$venv_dir" && ! -x "$venv_dir/bin/python" ]]; then
        die "$venv_dir exists but does not contain a valid virtual environment. Remove it and rerun setup."
    fi

    if [[ ! -d "$venv_dir" ]]; then
        log_info "  Creating virtualenv at $venv_dir"
        "$python_cmd" -m venv "$venv_dir"
    fi

    [[ -x "$venv_dir/bin/python" ]] || die "Failed to create $venv_dir"
}