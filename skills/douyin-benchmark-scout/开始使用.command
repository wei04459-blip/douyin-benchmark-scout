#!/bin/zsh
cd "${0:A:h}" || exit 1
if [[ -x "$HOME/.local/bin/python3.11" ]]; then
  "$HOME/.local/bin/python3.11" scripts/start.py
else
  python3 scripts/start.py
fi
echo
read "?按回车关闭…"
