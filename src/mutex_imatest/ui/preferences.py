"""Display preferences are separate from measurement settings and report data."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import json


@dataclass
class UiPreferences:
    language: str = 'system'
    theme: str = 'system'

    def validate(self):
        if self.language not in {'system', 'zh_CN', 'en'}:
            raise ValueError('Invalid UI language')
        if self.theme not in {'system', 'light', 'dark'}:
            raise ValueError('Invalid UI theme')
        return self


def preferences_file():
    # Resolve at call time: application tests redirect config_file to temporary
    # directories, and portable users keep their existing per-user location.
    from ..config import config_file
    return config_file().with_name('ui-preferences.json')


def load_preferences(path=None):
    try:
        data = json.loads(Path(path or preferences_file()).read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            return UiPreferences()
        return UiPreferences(**{key: data[key] for key in ('language', 'theme') if key in data}).validate()
    except (OSError, ValueError, TypeError):
        return UiPreferences()


def save_preferences(preferences, path=None):
    from ..utils import atomic_json
    preferences.validate()
    target = Path(path or preferences_file())
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(target, asdict(preferences))
