"""One ephemeral, permissive session choice; never restored from saved state."""
from urllib.parse import urlsplit, urlunsplit
from .policy import URLPolicy, PolicyError, config_value

START_PROMPT = ('Start fast discovery session: Y authorizes all current-session tool plans, including file writes, '
                'browser actions, code and inspected package execution, without repeated plan approval prompts; '
                'scoped read-only tools and useful S: knowledge saves run immediately; one prefilled login-button click '
                'is allowed; tool validation, browser ownership and operating-system approval still apply; '
                'sign-in and MFA stay manual. Approval resets for a fresh session [Y/n]? ')


def fast_mode(config):
    # Legacy internal flag is never enabled by the public session confirmation.
    # Keep it isolated from the scoped discovery grant for old embedded callers.
    return (config_value(config, '_permissive_session', False) is True
            and not discovery_mode(config))


def discovery_mode(config):
    return config_value(config, '_discovery_session', False) is True


def configure_session(config, allowed, *, approve_plans=False):
    config._session_plan_approval = bool(allowed and approve_plans)
    for name in ('_discovery_session', '_knowledge_session_confirmed', '_local_navigation_confirmed'):
        setattr(config, name, bool(allowed))
    for name in ('_permissive_session', '_supervised_session', '_continuous_package_session'):
        setattr(config, name, False)
    config._package_review_enabled = True
    config._session_approved_origins = set()


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
    if discovery_mode(config):
        return ApprovedWebsitePolicy(domains, config_value(config, '_session_approved_origins', ()))
    return OpenWebsitePolicy() if fast_mode(config) else URLPolicy(domains)


def website_origin(url):
    OpenWebsitePolicy.website_domain(url)
    parsed = urlsplit(url)
    host = parsed.hostname.lower().rstrip('.')
    host = '[' + host + ']' if ':' in host else host
    port = parsed.port
    return parsed.scheme + '://' + host + (':' + str(port) if port and port != (443 if parsed.scheme == 'https' else 80) else '')


class ApprovedWebsitePolicy(URLPolicy):
    """Default HTTPS domain scope plus exact separately approved origins."""
    def __init__(self, domains, origins):
        super().__init__(domains)
        self.origins = set(origins)

    def resolve(self, url):
        try:
            return super().resolve(url)
        except PolicyError:
            if website_origin(url) in self.origins:
                return urlunsplit(urlsplit(url))
            raise

    website_domain = staticmethod(OpenWebsitePolicy.website_domain)
