"""Model request limits shared by settings, core workers and the local gateway.

Counts describe simultaneous requests, not requests per minute or batch size.
The original core remains responsible for importing and embedding records.
"""
from urllib.parse import urlsplit


def default_concurrency(channel, model):
    return 20 if channel == 'xunfei' or (channel == 'zhipu' and model == 'glm-4-flash') else 4


def concurrency(profile):
    value = profile.get('concurrency', default_concurrency(profile['channel'], profile['model']))
    if type(value) is not int or not 1 <= value <= 64:
        raise ValueError('Model concurrency must be an integer between 1 and 64')
    return value


def model_scope(profile):
    """Group roles by the actual API base and model, independently of role/key.

    No credentials are included in cross-process slot names. Trailing slashes,
    hostname casing and the default HTTPS port must not create extra budgets.
    """
    parsed = urlsplit(profile['baseUrl'])
    host = (parsed.hostname or '').lower()
    port = parsed.port
    host = f'[{host}]' if ':' in host else host
    default_port = 443 if parsed.scheme.lower() == 'https' else 80
    authority = host if port in (None, default_port) else f'{host}:{port}'
    return f'{parsed.scheme.lower()}://{authority}{parsed.path.rstrip("/")}', profile['model']


def concurrency_environment(providers, active_roles=None):
    limits = {}
    for role, profile in providers.items():
        if role == 'search' or (active_roles is not None and role not in active_roles):
            continue
        if not profile.get('model') or not profile.get('baseUrl'):
            continue
        scope, limit = model_scope(profile), concurrency(profile)
        limits[scope] = min(limits.get(scope, limit), limit)

    def effective(role):
        profile = providers[role]
        return str(min(concurrency(profile), limits.get(model_scope(profile), 64)))

    main = effective('deepseek')
    small = effective('zhipu')
    return {
        'EMBEDDING_MAX_CONCURRENCY': effective('embedding'),
        'LABEL_MAX_CONCURRENCY': small,
        'ADAPTIVE_CHUNK_MAX_CONCURRENCY': small,
        'ANALYSIS_MAX_CONCURRENCY': main,
        'ANALYSIS_PROACTIVE_MAX_CONCURRENCY': main,
    }
