"""One ephemeral, permissive session choice; never restored from saved state."""
from urllib.parse import urlsplit, urlunsplit
from .policy import URLPolicy, PolicyError, config_value

START_PROMPT = 'Start fast full-access session: no package or plan review, reads and edits allowed, file deletion blocked [Y/n]? '


def fast_mode(config):
    return config_value(config, '_permissive_session', False) is True


def configure_session(config, allowed):
    for name in ('_permissive_session', '_supervised_session', '_continuous_package_session', '_local_navigation_confirmed'):
        setattr(config, name, bool(allowed))
    config._package_review_enabled = not allowed


class OpenWebsitePolicy(URLPolicy):
    """HTTP(S) browser access without a hostname, origin or port allowlist."""
    def __init__(self):
        super().__init__([])

    def resolve(self, url):
        self.website_domain(url)
        return urlunsplit(urlsplit(url))

    @staticmethod
    def website_domain(url):
        if not isinstance(url, str) or not url or len(url) > 16384 or any(ord(c) < 32 for c in url):
            raise PolicyError('Invalid website URL')
        try:
            parsed = urlsplit(url)
            if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError()
            parsed.port
        except ValueError as error:
            raise PolicyError('Use an HTTP(S) website URL without embedded credentials') from error
        return parsed.hostname.lower().rstrip('.')


def website_policy(config, domains=()):
    return OpenWebsitePolicy() if fast_mode(config) else URLPolicy(domains)
