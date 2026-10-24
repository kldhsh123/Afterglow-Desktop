"""Download public assets directly from GitHub and verify release hashes."""
import hashlib
import http.client
import urllib.error
import urllib.request
from urllib.parse import urlsplit

try:
    from .i18n import tr
except ImportError:
    from i18n import tr


NETWORK_ERRORS = (OSError, TimeoutError, http.client.HTTPException)


def github_url(url):
    if not isinstance(url, str):
        raise ValueError(tr('host.the_component_source_is_outside_the_builtin_allowlist'))
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.netloc != 'github.com' or parsed.username or parsed.password:
        raise ValueError(tr('host.the_component_source_is_outside_the_builtin_allowlist'))
    return url


def _connection_error(error):
    if isinstance(error, urllib.error.HTTPError):
        reason = 'HTTP ' + str(error.code)
    elif isinstance(error, TimeoutError):
        reason = tr('updates.connection_timeout')
    elif isinstance(error, urllib.error.URLError):
        reason = str(error.reason)
    elif isinstance(error, http.client.IncompleteRead):
        reason = tr('updates.download_interrupted')
    else:
        reason = str(error) or type(error).__name__
    return ValueError(tr('updates.github_unavailable', reason=reason))


def fetch_metadata(url, validate, max_bytes=1024 * 1024):
    url = github_url(url)
    try:
        with urllib.request.urlopen(url, timeout=12) as response:
            data = response.read(max_bytes + 1)
    except NETWORK_ERRORS as error:
        raise _connection_error(error) from None
    if len(data) > max_bytes:
        raise ValueError(tr('updates.invalid_catalog'))
    return validate(data)


def download_verified(url, destination, expected_sha256, max_bytes, executable=False):
    url = github_url(url)
    digest, total = hashlib.sha256(), 0
    try:
        with urllib.request.urlopen(url, timeout=30) as response, destination.open('wb') as output:
            while block := response.read(1024 * 1024):
                total += len(block)
                if total > max_bytes:
                    raise ValueError(tr('host.the_download_exceeds_the_size_limit'))
                digest.update(block)
                output.write(block)
        if digest.hexdigest().lower() != expected_sha256.lower():
            raise ValueError(tr('host.component_download_verification_failed'))
        if executable:
            with destination.open('rb') as stream:
                if stream.read(2) != b'MZ':
                    raise ValueError(tr('host.component_download_verification_failed'))
        return url
    except NETWORK_ERRORS as error:
        destination.unlink(missing_ok=True)
        raise _connection_error(error) from None
    except Exception:
        destination.unlink(missing_ok=True)
        raise
