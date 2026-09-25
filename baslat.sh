#!/bin/sh
# Instagram ajanı kontrol panelini açar. Botu panelden "Başlat" ile çalıştırın.
# Not: .venv içindeki `python` 3.14'ü gösteriyor ama paketler 3.12'de kurulu,
# bu yüzden 3.12 açıkça kullanılır.
cd "$(dirname "$0")" || exit 1
exec .venv/bin/python3.12 -m streamlit run ig_agent/control_panel.py "$@"
