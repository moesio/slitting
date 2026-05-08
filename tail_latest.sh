#!/usr/bin/env bash

ROOT_DIR="output"

tail_pid=""
current_file=""

start_tail() {
    local file="$1"

    [[ -f "$file" ]] || return

    # evita reiniciar no mesmo arquivo
    [[ "$file" == "$current_file" ]] && return

    echo ">>> Novo arquivo detectado: $file"

    # encerra tail anterior
    if [[ -n "$tail_pid" ]] && kill -0 "$tail_pid" 2>/dev/null; then
        kill "$tail_pid"
        wait "$tail_pid" 2>/dev/null
    fi

    current_file="$file"

    echo ">>> Monitorando: $current_file"

    tail -F -v -- "$current_file" &
    tail_pid=$!
}

# cleanup ao sair
cleanup() {
    if [[ -n "$tail_pid" ]] && kill -0 "$tail_pid" 2>/dev/null; then
        kill "$tail_pid"
    fi
}

trap cleanup EXIT

# pega o arquivo mais recente já existente
latest_existing=$(
    find "$ROOT_DIR" -type f -printf '%T@ %p\n' 2>/dev/null \
    | sort -nr \
    | head -n1 \
    | cut -d' ' -f2-
)

[[ -n "$latest_existing" ]] && start_tail "$latest_existing"

# monitora novos arquivos recursivamente
inotifywait -m -r \
    -e create \
    -e moved_to \
    --format '%w%f' \
    "$ROOT_DIR" |
while read -r file; do
    start_tail "$file"
done
