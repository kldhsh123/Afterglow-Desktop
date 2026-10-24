"""Machine-readable worker events; never interpolate provider credentials in logs."""
import json

PREFIX = "AFTERGLOW_EVENT:"


def emit(event, **data):
    print(PREFIX + json.dumps({"event": event, **data}, ensure_ascii=False), flush=True)
