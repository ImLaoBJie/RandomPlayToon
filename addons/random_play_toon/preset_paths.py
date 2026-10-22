"""One source for character configuration; releases bundle it with the add-on."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent / 'presets'
if not (ROOT / 'catalog.json').is_file():
    ROOT = Path(__file__).resolve().parents[2] / 'presets'
