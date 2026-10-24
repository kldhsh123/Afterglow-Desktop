"""Shared locale files for native manager messages and the Vue interface."""
from contextvars import ContextVar
from functools import lru_cache
import json
from pathlib import Path
import re

_language = ContextVar("afterglow_locale", default="zh-CN")
LOCALES = Path(__file__).resolve().parent.parent / "locales"


def set_language(value):
    _language.set(value if value in {"zh-CN", "en-US"} else "zh-CN")


@lru_cache(maxsize=2)
def dictionary(language):
    return json.loads((LOCALES / (language + ".json")).read_text(encoding="utf-8"))


def tr(key, **args):
    text = dictionary(_language.get()).get(key, dictionary("zh-CN").get(key, key))
    return re.sub(r"\{([A-Za-z0-9_]+)\}", lambda m: str(args.get(m[1], m[0])), text)
