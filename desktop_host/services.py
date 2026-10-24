"""Desktop configuration of optional services implemented by the original core."""
from urllib.parse import urlencode
import json
import urllib.request

try:
    from .model_gateway import NoRedirect
    from .i18n import tr
except ImportError:
    from model_gateway import NoRedirect
    from i18n import tr

MODEL_ROLES = {"deepseek", "embedding", "rerank", "zhipu", "vision", "imageImportVision", "search"}


def required_roles(settings):
    roles = ["deepseek", "embedding", "zhipu"]
    if settings["features"]["rerank"]:
        roles.append("rerank")
    if settings["services"]["vision"] == "separate":
        roles.append("vision")
    if settings["services"].get("imageImportVision"):
        roles.append("imageImportVision")
    if settings["services"]["webSearch"]:
        roles.append("search")
    return roles


def key_required(role, profile):
    return role != "search" or profile["channel"] != "searxng"


def image_import_environment(settings, gateway, token):
    """Only the offline image worker receives the dedicated vision profile."""
    if not settings.get('services', {}).get('imageImportVision'):
        return {}
    profile = settings['providers']['imageImportVision']
    return {'VISION_ENABLED': 'true', 'CHAT_MODEL_SUPPORTS_VISION': 'false',
            'VISION_API_URL': gateway.base('custom_imageImportVision'),
            'VISION_API_KEY': token, 'VISION_MODEL': profile['model']}


def optional_environment(settings, gateway, token, get_key, locale):
    services, profiles = settings["services"], settings["providers"]
    vision, search = profiles["vision"], profiles["search"]
    return {
        "VISION_ENABLED": str(services["vision"] != "off").lower(),
        "CHAT_MODEL_SUPPORTS_VISION": str(services["vision"] == "main").lower(),
        "VISION_API_URL": gateway.base("custom_deepseek" if services["vision"] == "main" else "custom_vision"),
        "VISION_API_KEY": token,
        "VISION_MODEL": profiles["deepseek"]["model"] if services["vision"] == "main" else vision["model"],
        "WEB_ACCESS_ENABLED": str(services["webSearch"] or services["webFetch"]).lower(),
        "WEB_SEARCH_PROVIDER": search["channel"],
        "WEB_SEARCH_BASE_URL": search["baseUrl"],
        "WEB_SEARCH_API_KEY": get_key("search", search) if services["webSearch"] else "",
        "WEB_SEARCH_MAX_RESULTS": "5" if services["webSearch"] else "0",
        "WEB_SEARCH_LANGUAGE": locale,
        "WEB_FETCH_ENABLED": str(services["webFetch"]).lower(),
    }


def search_test(profile, key, locale):
    url = profile["baseUrl"].rstrip("/") + "/search"
    headers = {"Content-Type": "application/json"}
    if profile["channel"] == "tavily":
        data = json.dumps({"api_key": key, "query": "Afterglow", "max_results": 1, "search_depth": "basic", "include_answer": False, "include_raw_content": False}).encode()
    else:
        data = None
        url += "?" + urlencode({"q": "Afterglow", "format": "json", "language": locale})
        if key:
            headers["Authorization"] = "Bearer " + key
    with urllib.request.build_opener(NoRedirect).open(urllib.request.Request(url, data, headers), timeout=15) as response:
        payload = json.loads(response.read(2 * 1024 * 1024))
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError(tr("services.invalid_search_response"))
    return {"ok": True, "message": tr("services.search_test_passed")}
