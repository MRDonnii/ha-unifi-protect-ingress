import asyncio
import gzip
import html
import ipaddress
import json
import logging
import os
import re
import secrets
import ssl
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from aiohttp import (ClientSession, ClientTimeout, TCPConnector, WSMsgType,
                     WSServerHandshakeError, web)

OPTIONS = Path(os.environ.get("OPTIONS_PATH", "/data/options.json"))
COOKIE_STORE = Path(os.environ.get("COOKIE_STORE_PATH", "/data/upstream-cookies.json"))
TOKEN_STORE = Path(os.environ.get("TOKEN_STORE_PATH", "/data/root-proxy-token"))
cfg = json.loads(OPTIONS.read_text())
UPSTREAM = cfg["protect_url"].rstrip("/")
START_PATH = "/" + cfg.get("start_path", "/protect/").lstrip("/")
REWRITE_PATHS = sorted(set(cfg.get("rewrite_paths", [])), key=len, reverse=True)
VERIFY_SSL = cfg.get("verify_ssl", False)
DEBUG = cfg.get("debug", False)
PUBLIC_URL = cfg.get("public_url", "").strip().rstrip("/")
BACK_BUTTON_ENABLED = cfg.get("back_button_enabled", False)
NAVBAR_ENABLED = cfg.get("navbar_enabled", False)
UP = urlsplit(UPSTREAM)
UP_ORIGIN = f"{UP.scheme}://{UP.netloc}"
CDN_ORIGIN = "https://cdn.pkg.svc.ui.com"
CDN = urlsplit(CDN_ORIGIN)
CDN_PREFIX = "/_unifi_cdn"
ROOT_AUTH_COOKIE = "ha_protect_proxy"

logging.basicConfig(level=logging.DEBUG if DEBUG else logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("protect-ingress")


def load_access_token():
    try:
        token = TOKEN_STORE.read_text().strip()
        if len(token) >= 32:
            return token
    except OSError:
        pass
    token = secrets.token_urlsafe(32)
    try:
        TOKEN_STORE.write_text(token)
        TOKEN_STORE.chmod(0o600)
    except OSError:
        LOG.warning("Could not persist the root-proxy access token")
    return token


ACCESS_TOKEN = load_access_token()


def normalize_back_button_target(value):
    """Return an HA path or absolute HTTP(S) URL safe for top-level navigation."""
    value = str(value or "/").strip()
    parsed = urlsplit(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return value
    # Treat friendly values such as `lovelace/home` as HA-root-relative paths.
    # Protocol-relative URLs are deliberately reduced to a local path.
    return "/" + value.lstrip("/") if value.strip("/") else "/"


BACK_BUTTON_TARGET = normalize_back_button_target(
    cfg.get("back_button_target", "/")
)


def parse_navbar_config(items, subitems):
    """Parse compact, user-editable navbar entries from the add-on options."""
    routes = []
    groups = {}
    for raw in items or []:
        parts = [part.strip() for part in str(raw).split("|", 2)]
        if len(parts) != 3 or not parts[1]:
            LOG.warning("Ignoring invalid navbar item: %r", raw)
            continue
        icon, label, target = parts
        route = {
            "icon": icon.removeprefix("mdi:"),
            "label": label,
            "target": normalize_back_button_target(target) if target else "",
            "items": [],
        }
        routes.append(route)
        groups[label.casefold()] = route
    for raw in subitems or []:
        parts = [part.strip() for part in str(raw).split("|", 3)]
        if len(parts) != 4 or not parts[0] or not parts[2] or not parts[3]:
            LOG.warning("Ignoring invalid navbar submenu item: %r", raw)
            continue
        group, icon, label, target = parts
        parent = groups.get(group.casefold())
        if not parent:
            LOG.warning("Ignoring submenu item for unknown navbar group %r", group)
            continue
        parent["items"].append({
            "icon": icon.removeprefix("mdi:"),
            "label": label,
            "target": normalize_back_button_target(target),
        })
    return routes


NAVBAR_ROUTES = parse_navbar_config(
    cfg.get("navbar_items", []), cfg.get("navbar_subitems", [])
)


ICON_PATHS = {
    "home": "M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z",
    "home-outline": "M12 5.69 17 10.19V18h-2v-6H9v6H7v-7.81zM12 3 2 12h3v8h6v-6h2v6h6v-8z",
    "floor-plan": "M3 3h8v2H5v6h6v8h8v-6h-4v-2h6v10H9v-8H3zm10 0h8v6h-2V5h-6z",
    "home-heart": "M12 3 2 12h3v8h14v-8h3zm0 4.1 5 4.5V18H7v-6.4zM12 17s-3-1.8-3-4a2 2 0 0 1 3-1.7A2 2 0 0 1 15 13c0 2.2-3 4-3 4",
    "play-circle": "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20m-2 14.5v-9l6 4.5z",
    "play-circle-outline": "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20m0 18a8 8 0 1 1 0-16 8 8 0 0 1 0 16m-2-3.5 6-4.5-6-4.5z",
    "machine-image": "M4 4h16v16H4zm2 2v8l3-3 3 3 2-2 4 4V6zm1 11h10l-5-5-2 2-1-1z",
    "account-group": "M16 13c2.67 0 8 1.34 8 4v3h-8v-3c0-1.13-.44-2.1-1.18-2.9C15.22 14.03 15.61 14 16 14m-8-1a4 4 0 1 0 0-8 4 4 0 0 0 0 8m0 2c-2.67 0-8 1.34-8 4v2h14v-2c0-2.66-5.33-4-8-4m8-2a3 3 0 1 0 0-6 3 3 0 0 0 0 6",
    "cog": "M19.43 12.98c.04-.32.07-.65.07-.98s-.03-.66-.08-.98l2.11-1.65-2-3.46-2.49 1a7.2 7.2 0 0 0-1.69-.98L15 3.27h-4l-.39 2.66c-.61.25-1.17.59-1.69.98l-2.49-1-2 3.46 2.11 1.65c-.05.32-.08.66-.08.98s.03.66.08.98l-2.11 1.65 2 3.46 2.49-1c.52.4 1.08.73 1.69.98l.39 2.66h4l.39-2.66c.61-.25 1.17-.58 1.69-.98l2.49 1 2-3.46zM13 15.5a3.5 3.5 0 1 1 0-7 3.5 3.5 0 0 1 0 7",
    "cog-outline": "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8m0 6a2 2 0 1 1 0-4 2 2 0 0 1 0 4m8.94-2.66-1.72-1.34.04-.5.01-.5-.05-1-1.72-1.34.94-2.08-1.41-1.41-2.08.94L13.66 2h-2.32L10 4.11l-2.08-.94-1.41 1.41L7.45 6.66 5.73 8l-.05 1 .05 1 1.72 1.34-.94 2.08 1.41 1.41 2.08-.94 1.34 1.72h2.32L15 13.89l2.08.94 1.41-1.41z",
    "camera": "M9 3 7.17 5H4a2 2 0 0 0-2 2v12h20V7a2 2 0 0 0-2-2h-3.17L15 3zm3 5a5 5 0 1 1 0 10 5 5 0 0 1 0-10",
    "cctv": "M4 4h16v12H4zm2 2v8h12V6zm2 12h8v2H8z",
    "settings": "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8",
}


def navbar_icon(name):
    """Return a self-contained SVG; unknown icons get a neutral circle."""
    path = ICON_PATHS.get(name, "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18m0 5a4 4 0 1 1 0 8 4 4 0 0 1 0-8")
    return (
        '<svg viewBox="0 0 24 24" aria-hidden="true">'
        f'<path d="{path}"/></svg>'
    )


def navbar_markup(routes):
    if not NAVBAR_ENABLED or not routes:
        return "", ""
    rendered = []
    for index, route in enumerate(routes):
        label = html.escape(route["label"], quote=True)
        icon = navbar_icon(route["icon"])
        if route["items"]:
            popup_items = []
            for child in route["items"]:
                child_label = html.escape(child["label"], quote=True)
                child_target = html.escape(child["target"], quote=True)
                popup_items.append(
                    f'<a class="ha-nav-subitem" href="{child_target}" target="_top">'
                    f'{navbar_icon(child["icon"])}<span>{child_label}</span></a>'
                )
            rendered.append(
                f'<div class="ha-nav-route"><button class="ha-nav-button" type="button" '
                f'data-navbar-popup="navbar-popup-{index}" aria-expanded="false" '
                f'aria-label="{label}" title="{label}">{icon}</button>'
                f'<div class="ha-nav-popup" id="navbar-popup-{index}" hidden>'
                f'<div class="ha-nav-popup-title">{label}</div>{"".join(popup_items)}</div></div>'
            )
        else:
            target = html.escape(route["target"], quote=True)
            rendered.append(
                f'<a class="ha-nav-button" href="{target}" target="_top" '
                f'aria-label="{label}" title="{label}">{icon}</a>'
            )
    markup = (
        '<nav id="ha-navbar" aria-label="Home Assistant navigation">'
        '<div class="ha-navbar-card">' + "".join(rendered) + '</div></nav>'
    )
    script = """document.querySelectorAll('[data-navbar-popup]').forEach(b=>b.addEventListener('click',e=>{e.stopPropagation();const id=b.dataset.navbarPopup,p=document.getElementById(id),open=p.hidden;document.querySelectorAll('.ha-nav-popup').forEach(x=>x.hidden=true);document.querySelectorAll('[data-navbar-popup]').forEach(x=>x.setAttribute('aria-expanded','false'));p.hidden=!open;b.setAttribute('aria-expanded',String(open))}));document.addEventListener('click',()=>{document.querySelectorAll('.ha-nav-popup').forEach(x=>x.hidden=true);document.querySelectorAll('[data-navbar-popup]').forEach(x=>x.setAttribute('aria-expanded','false'))});document.addEventListener('keydown',e=>{if(e.key==='Escape')document.dispatchEvent(new Event('click'))});"""
    return markup, script


def public_entry_url():
    if not PUBLIC_URL:
        return ""
    parsed = urlsplit(PUBLIC_URL)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("public_url must be an absolute HTTPS URL")
    if parsed.path not in ("", "/"):
        return PUBLIC_URL
    return PUBLIC_URL + START_PATH


PUBLIC_ENTRY = public_entry_url()


def embedded_wrapper():
    if PUBLIC_ENTRY:
        parsed_entry = urlsplit(PUBLIC_ENTRY)
        public_origin = f"{parsed_entry.scheme}://{parsed_entry.netloc}"
        target_script = (
            json.dumps(public_origin + "/__ha_auth?token=")
            + "+encodeURIComponent(" + json.dumps(ACCESS_TOKEN) + ")"
            + "+'&next='+encodeURIComponent(" + json.dumps(parsed_entry.path or START_PATH) + ")"
        )
        origin = urlsplit(PUBLIC_ENTRY)
        frame_sources = f"{origin.scheme}://{origin.netloc}"
    else:
        # Use the same host through which the user opened HA, but the add-on's
        # exposed root-proxy port. This works on LAN and over a private VPN without
        # requiring every installation to hard-code its Home Assistant address.
        target_script = (
            "location.protocol+'//'+location.hostname+':8099/__ha_auth?token='"
            "+encodeURIComponent(" + json.dumps(ACCESS_TOKEN) + ")"
            "+'&next='+encodeURIComponent(" + json.dumps(START_PATH) + ")"
        )
        frame_sources = "http: https:"
    back_button = ""
    back_script = ""
    if BACK_BUTTON_ENABLED:
        back_button = """<button id="ha-back" type="button" title="Back to Home Assistant" aria-label="Back to Home Assistant">
<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.42-1.41L7.83 13H20v-2z"/></svg>
</button>"""
        target_json = json.dumps(BACK_BUTTON_TARGET).replace("<", "\\u003c")
        back_script = (
            "document.getElementById('ha-back').addEventListener('click',()=>"
            "window.open(" + target_json + ",'_top'));"
        )
    navbar, navbar_script = navbar_markup(NAVBAR_ROUTES)
    body = f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>UniFi Protect</title><style>
html,body,iframe{{width:100%;height:100%;margin:0;border:0;background:#f7f8fa;overflow:hidden}}
#ha-back{{position:fixed;top:max(12px,env(safe-area-inset-top));left:max(12px,env(safe-area-inset-left));z-index:2147483647;width:46px;height:46px;padding:0;border:1px solid rgba(255,255,255,.28);border-radius:50%;background:#071b38e8;color:#fff;display:grid;place-items:center;cursor:pointer;box-shadow:0 5px 18px rgba(0,0,0,.28);backdrop-filter:blur(6px)}}
#ha-back:hover{{background:#0b63ce}}#ha-back:focus-visible{{outline:3px solid #18c8ff;outline-offset:2px}}#ha-back svg{{width:25px;height:25px;fill:currentColor}}
#ha-navbar{{position:fixed;z-index:2147483646;left:50%;bottom:max(18px,env(safe-area-inset-bottom));transform:translateX(-50%);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#f5f7fb}}
.ha-navbar-card{{display:flex;align-items:center;gap:3px;padding:9px 11px;border:1px solid rgba(255,255,255,.09);border-radius:24px;background:linear-gradient(180deg,rgba(255,255,255,.05),rgba(255,255,255,.015)),rgba(19,25,34,.96);box-shadow:0 10px 28px rgba(0,0,0,.28)}}
.ha-nav-route{{position:relative}}.ha-nav-button{{width:58px;height:58px;box-sizing:border-box;border:0;border-radius:17px;background:transparent;color:#dfe5ee;display:grid;place-items:center;cursor:pointer;text-decoration:none;transition:background .16s,transform .16s,color .16s}}
.ha-nav-button:hover,.ha-nav-button[aria-expanded="true"]{{background:rgba(255,255,255,.08);color:#45a3ff;transform:translateY(-1px)}}.ha-nav-button:focus-visible{{outline:3px solid #18c8ff;outline-offset:1px}}
.ha-nav-button svg{{width:28px;height:28px;fill:currentColor}}.ha-nav-popup{{position:absolute;left:50%;bottom:72px;transform:translateX(-50%);min-width:220px;max-height:min(62vh,520px);overflow:auto;padding:9px;border:1px solid rgba(255,255,255,.09);border-radius:24px;background:linear-gradient(180deg,rgba(255,255,255,.05),rgba(255,255,255,.015)),rgba(19,25,34,.98);box-shadow:0 18px 38px rgba(0,0,0,.34)}}
.ha-nav-popup[hidden]{{display:none}}.ha-nav-popup-title{{padding:8px 11px;color:#8f9aaa;font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.06em}}.ha-nav-subitem{{display:flex;align-items:center;gap:12px;min-height:46px;padding:4px 11px;border-radius:16px;color:#f5f7fb;text-decoration:none;font-size:14px;font-weight:700;white-space:nowrap}}.ha-nav-subitem:hover{{background:rgba(255,255,255,.07)}}.ha-nav-subitem svg{{width:22px;height:22px;flex:none;fill:currentColor;color:#aeb8c7}}
@media(max-width:768px){{#ha-navbar{{bottom:max(20px,env(safe-area-inset-bottom));width:calc(100vw - 24px)}}.ha-navbar-card{{overflow-x:auto;justify-content:space-around;padding:8px;border-radius:22px;scrollbar-width:none}}.ha-navbar-card::-webkit-scrollbar{{display:none}}.ha-nav-button{{width:48px;height:52px;border-radius:15px}}.ha-nav-button svg{{width:25px;height:25px}}.ha-nav-popup{{position:fixed;left:12px;right:12px;bottom:84px;transform:none;min-width:0}}}}
</style></head><body>{back_button}{navbar}<iframe id="protect" title="UniFi Protect" allow="fullscreen; autoplay" referrerpolicy="same-origin"></iframe>
<script>{back_script}{navbar_script}document.getElementById('protect').src={target_script};</script></body></html>"""
    return web.Response(
        text=body,
        content_type="text/html",
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": f"frame-ancestors *; frame-src {frame_sources}",
        },
    )

DROP_REQUEST = {"host", "connection", "upgrade", "content-length", "accept-encoding"}
DROP_RESPONSE = {"connection", "transfer-encoding", "content-length", "content-encoding",
                 "x-frame-options", "content-security-policy", "content-security-policy-report-only"}
TEXT_TYPES = ("text/html", "text/css", "text/javascript", "application/javascript",
              "application/x-javascript", "application/json", "application/manifest+json")


def load_default_cookies():
    try:
        data = json.loads(COOKIE_STORE.read_text())
        return {str(key): str(value) for key, value in data.items()}
    except (OSError, ValueError, TypeError):
        return {}


def save_default_cookies(jar):
    try:
        COOKIE_STORE.write_text(json.dumps(jar))
        COOKIE_STORE.chmod(0o600)
    except OSError:
        LOG.warning("Could not persist the upstream session cookie")


def ingress_base(request):
    value = request.headers.get("X-Ingress-Path", "").rstrip("/")
    return value


def upstream_path(request):
    # Supervisor ingress can combine its entry and the app entry with extra slashes.
    raw_path = request.path
    path = re.sub(r"/{2,}", "/", raw_path)
    if raw_path == "/protect":
        path = "/protect/dashboard"
    elif path in ("/", "/protect", "/protect/"):
        path = START_PATH
    # Some Protect bundles navigate using root-relative SPA routes even when their
    # router basename was patched. Since this add-on exposes Protect exclusively,
    # resolve those bare UI routes to the Protect application on the server too.
    elif re.match(
        r"^/(?:dashboard|detections(?:/|$)|devices(?:/|$)|timelapse(?:/|$)|"
        r"cases(?:/|$)|vantage-points(?:/|$)|settings(?:/|$)|syslog(?:/|$)|"
        r"alarms(?:/|$)|integrations(?:/|$)|innerspace(?:/|$)|admins(?:/|$))",
        path,
    ):
        path = "/protect" + path
    query = ("?" + request.query_string) if request.query_string else ""
    return path + query


def request_headers(request):
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in DROP_REQUEST
        and k.lower() != "x-ingress-path"
        and not k.lower().startswith("x-hassio-")
        and not k.lower().startswith("x-forwarded-")
    }
    headers["Host"] = UP.netloc
    headers["Accept-Encoding"] = "identity"
    # Supervisor's session cookie authenticates HA ingress, not UniFi. Passing it to
    # UniFi makes recent console versions reject an otherwise valid login as malformed.
    if "Cookie" in headers:
        cookie = SimpleCookie()
        cookie.load(headers["Cookie"])
        cookie.pop("ingress_session", None)
        rendered = "; ".join(f"{key}={morsel.value}" for key, morsel in cookie.items())
        if rendered:
            headers["Cookie"] = rendered
        else:
            headers.pop("Cookie", None)
    # Supervisor may suppress or browsers may reject the console's cookies under an
    # HTTP ingress origin. Keep a separate upstream cookie jar per HA ingress session.
    ingress_session = request.cookies.get("ingress_session")
    stored = request.app.get("upstream_cookies", {}).get(ingress_session)
    if not stored:
        # Supervisor can rotate ingress_session during an iframe reload. Keep the
        # authenticated console session usable across that rotation.
        stored = request.app.get("default_upstream_cookies", {})
    if stored:
        cookie = SimpleCookie()
        if "Cookie" in headers:
            cookie.load(headers["Cookie"])
        for key, value in stored.items():
            cookie[key] = value
        headers["Cookie"] = "; ".join(
            f"{key}={morsel.value}" for key, morsel in cookie.items()
        )
    if "Origin" in headers:
        headers["Origin"] = UP_ORIGIN
    if "Referer" in headers:
        ref_path = urlsplit(headers["Referer"]).path
        base = ingress_base(request)
        if base and ref_path.startswith(base):
            ref_path = ref_path[len(base):] or "/"
        headers["Referer"] = urljoin(UP_ORIGIN, ref_path)
    if request.path.startswith("/api/auth/"):
        # Match a direct console login closely. Supervisor/browser-specific headers can
        # make UniFi OS reject the request as malformed before checking credentials.
        allowed = {"host", "accept", "accept-language", "content-type", "origin",
                   "referer", "user-agent", "cookie", "accept-encoding"}
        headers = {key: value for key, value in headers.items() if key.lower() in allowed}
    return headers


def remember_upstream_cookies(request, upstream):
    ingress_session = request.cookies.get("ingress_session")
    jar = request.app["upstream_cookies"].setdefault(ingress_session, {}) if ingress_session else {}
    default_jar = request.app["default_upstream_cookies"]
    for value in upstream.headers.getall("Set-Cookie", []):
        parsed = SimpleCookie()
        parsed.load(value)
        if parsed:
            candidates = [(key, morsel.value, morsel["max-age"] == "0")
                          for key, morsel in parsed.items()]
        else:
            # Some UniFi OS releases emit attributes SimpleCookie refuses to parse.
            match = re.match(r"\s*([^=;\s]+)=([^;]*)", value)
            candidates = [(match.group(1), match.group(2),
                           bool(re.search(r";\s*Max-Age=0(?:;|$)", value, re.I)))] if match else []
        for key, cookie_value, expired in candidates:
            if expired or not cookie_value:
                jar.pop(key, None)
                default_jar.pop(key, None)
            else:
                jar[key] = cookie_value
                default_jar[key] = cookie_value
    if DEBUG and upstream.headers.getall("Set-Cookie", []):
        LOG.debug("Stored upstream cookie names for ingress session: %s", sorted(jar))
    if upstream.headers.getall("Set-Cookie", []):
        save_default_cookies(default_jar)


def rewrite_location(value, base):
    if value.startswith(UP_ORIGIN):
        value = value[len(UP_ORIGIN):] or "/"
    if value.startswith("/") and base and not value.startswith(base + "/"):
        return base + value
    return value


def rewrite_cookie(value, base, secure_client=True):
    # Keep upstream auth in the HA ingress scope and remove a controller-specific Domain.
    value = re.sub(r";\s*Domain=[^;]+", "", value, flags=re.I)
    if not secure_client:
        value = re.sub(r";\s*Secure\b", "", value, flags=re.I)
        value = re.sub(r"(;\s*SameSite=)None\b", r"\1Lax", value, flags=re.I)
    scoped = (base + "/") if base else "/"
    if re.search(r";\s*Path=", value, flags=re.I):
        value = re.sub(r"(;\s*Path=)[^;]*", lambda m: m.group(1) + scoped, value,
                       flags=re.I)
    else:
        value += "; Path=" + scoped
    return value


def rewrite_body(data, content_type, base):
    if not base or not any(content_type.startswith(t) for t in TEXT_TYPES):
        return data
    text = data.decode("utf-8", errors="replace")
    # Protect's SWAI frontend is loaded from UniFi's CDN. Loading it directly from
    # an HTTP HA iframe can fail before the Protect module starts, so keep it on the
    # same ingress origin and proxy the CDN through this add-on as well.
    text = text.replace(CDN_ORIGIN, base + CDN_PREFIX)
    is_javascript = content_type.startswith(
        ("text/javascript", "application/javascript", "application/x-javascript")
    )
    if is_javascript:
        # Rspack's runtime uses `/` as its public path for lazy-loaded chunks. A script
        # element cannot be caught by the fetch/XHR shim, so point the runtime itself at
        # the current Supervisor ingress prefix.
        text = text.replace('.p="/"', '.p=' + json.dumps(base + "/"))
        # UniFi OS uses React Router without a basename. Under Supervisor ingress the real
        # pathname starts with a per-session prefix, so teach the bundled browser history to
        # strip/add that prefix while leaving Protect's own routes unchanged.
        basename_expr = 'e.basename?l(s(e.basename)):""'
        text = text.replace(
            basename_expr,
            'e.basename?l(s(e.basename)):' + json.dumps(base),
        )
        # Protect's own SWAI bundle creates a second browser history. In local mode
        # its basename is empty, so it otherwise sees the Supervisor ingress token
        # as part of the Protect route and renders its internal 404 page.
        text = text.replace(
            "const d=(0,i.zR)({basename:n})",
            "const d=(0,i.zR)({basename:" + json.dumps(base + "/protect") + "})",
        )
    # UniFi OS emits fingerprinted bundles and assets directly below `/` (their names change
    # between firmware releases), so a fixed allow-list is insufficient. Prefix every quoted
    # root-relative URL while leaving protocol-relative URLs and already-scoped URLs untouched.
    if content_type.startswith("text/html"):
        escaped_base = re.escape(base.lstrip("/"))
        text = re.sub(
            rf"([\"'])(/(?!/|{escaped_base}(?:/|[\"'])))",
            lambda match: match.group(1) + base + match.group(2),
            text,
        )
        # UniFi fingerprints its bundles but our rewritten response can change without the
        # upstream filename changing. Bust browser copies produced by an earlier proxy build.
        def cache_bust(match):
            prefix, url, quote = match.groups()
            if re.search(r"\.(?:js|css)(?:\?|$)", url, flags=re.I):
                url += ("&" if "?" in url else "?") + "ha_ingress_proxy=8"
            return prefix + url + quote

        text = re.sub(r"((?:src|href)=[\"'])([^\"']+)([\"'])", cache_bust, text,
                      flags=re.I)
    if content_type.startswith("text/css"):
        text = re.sub(r"url\((['\"]?)/(?!/)", lambda m: "url(" + m.group(1) + base + "/", text)
    # Longest first prevents /protect from touching /proxy/protect after replacement.
    if not is_javascript:
        for path in REWRITE_PATHS:
            prefixed = base + path
            text = text.replace('"' + path, '"' + prefixed)
            text = text.replace("'" + path, "'" + prefixed)
            text = text.replace("url(" + path, "url(" + prefixed)
            text = text.replace("url('" + path, "url('" + prefixed)
            text = text.replace('url("' + path, 'url("' + prefixed)
    if content_type.startswith("text/html"):
        # Covers paths assembled at runtime and browser APIs that static replacement misses.
        paths = json.dumps(REWRITE_PATHS)
        shim = """<script>(function(){const B=%s,P=%s,A=/^\\/(?:dashboard|detections(?:\\/|$)|devices(?:\\/|$)|timelapse(?:\\/|$)|cases(?:\\/|$)|vantage-points(?:\\/|$)|settings(?:\\/|$)|syslog(?:\\/|$)|alarms(?:\\/|$)|integrations(?:\\/|$)|innerspace(?:\\/|$)|admins(?:\\/|$))/;const n=u=>{if(typeof u!==\"string\")return u;while(u.startsWith(B+B))u=u.slice(B.length);if(u.startsWith(B+'//'))u=B+u.slice(B.length).replace(/^\\/+/,'/');return u};const r=u=>{u=n(u);if(typeof u!==\"string\")return u;if(u.startsWith(B+'/')){const s=u.slice(B.length);return A.test(s)?B+'/protect'+s:u}if(u.startsWith('/')&&!u.startsWith('//'))return B+(A.test(u)?'/protect':'')+u;return u};const hp=history.pushState.bind(history),hr=history.replaceState.bind(history);const clean=n(location.pathname)+location.search+location.hash;if(clean!==location.pathname+location.search+location.hash)hr(history.state,'',clean);history.pushState=function(s,t,u){return hp(s,t,r(u))};history.replaceState=function(s,t,u){return hr(s,t,r(u))};addEventListener('click',e=>{const a=e.target&&e.target.closest&&e.target.closest('a[href]');if(!a)return;const x=new URL(a.href,location.href);if(x.origin!==location.origin)return;let p=n(x.pathname);if(p===B+'/protect'||p===B+'/protect/')p=B+'/protect/dashboard';else if(p.startsWith(B+'/')){const s=p.slice(B.length);if(A.test(s))p=B+'/protect'+s}if(p!==x.pathname||p===B+'/protect/dashboard'){e.preventDefault();e.stopImmediatePropagation();location.assign(p+x.search+x.hash)}},true);if(location.pathname.endsWith('/protect/'))hr(history.state,'',B+'/login?redirect=%%2Fprotect%%2Fdashboard');else if(location.pathname.endsWith('/protect'))hr(history.state,'',B+'/protect/dashboard');const f=window.fetch;window.fetch=function(i,o){return f.call(this,typeof i===\"string\"?r(i):i,o)};const xo=XMLHttpRequest.prototype.open;XMLHttpRequest.prototype.open=function(m,u){arguments[1]=r(u);return xo.apply(this,arguments)};const W=window.WebSocket;window.WebSocket=function(u,p){const x=new URL(u,location.href);x.pathname=r(x.pathname);return new W(x,p)};window.WebSocket.prototype=W.prototype;})();</script>""" % (json.dumps(base), paths)
        shim = shim.replace(
            "const B=", 
            "document.addEventListener('error',e=>{if(e.target&&e.target.tagName==='SCRIPT')console.error('Protect ingress script failed:',e.target.src)},true);const B=",
            1,
        )
        shim = shim.replace(
            "const f=window.fetch;",
            "const dc=document.createElement.bind(document);document.createElement=function(t,...a){const e=dc(t,...a);if(String(t).toLowerCase()==='script')Object.defineProperty(e,'src',{configurable:true,get(){return this.getAttribute('src')||''},set(v){this.setAttribute('src',r(v))}});return e};const f=window.fetch;",
            1,
        )
        text = re.sub(r"(<head(?:\s[^>]*)?>)", r"\1" + shim, text, count=1, flags=re.I)
    return text.encode("utf-8")


def copy_response_headers(response, upstream, base, content_type, rewritten, secure_client=True):
    for key, value in upstream.headers.items():
        lower = key.lower()
        if lower in {"connection", "transfer-encoding", "x-frame-options",
                     "content-security-policy", "content-security-policy-report-only"}:
            continue
        if lower in {"set-cookie", "content-length"} or (rewritten and lower == "content-encoding"):
            continue
        if lower == "location":
            value = rewrite_location(value, base)
        response.headers.add(key, value)
    for value in upstream.headers.getall("Set-Cookie", []):
        response.headers.add("Set-Cookie", rewrite_cookie(value, base, secure_client))
    response.headers["Content-Security-Policy"] = "frame-ancestors *"
    if rewritten:
        response.headers["Cache-Control"] = "no-store"


async def websocket_proxy(request, session, target):
    protocols = [p.strip() for p in request.headers.get("Sec-WebSocket-Protocol", "").split(",") if p.strip()]
    try:
        upstream = await session.ws_connect(
            target, headers=request_headers(request), protocols=protocols,
            autoping=False, autoclose=False, heartbeat=30,
        )
    except WSServerHandshakeError as exc:
        LOG.info("Upstream rejected WebSocket %s with HTTP %s", target, exc.status)
        return web.Response(status=exc.status, text="Upstream WebSocket authentication required")
    except Exception:
        LOG.exception("WebSocket proxy failed: %s", target)
        return web.Response(status=502, text="Upstream WebSocket failed")

    downstream = web.WebSocketResponse(protocols=protocols, autoclose=False, autoping=False)
    await downstream.prepare(request)
    base = ingress_base(request)
    cdn_from_text = CDN_ORIGIN
    cdn_to_text = base + CDN_PREFIX
    cdn_from_bytes = CDN_ORIGIN.encode()
    cdn_to_bytes = cdn_to_text.encode()
    try:
        async def pump(source, destination, rewrite_cdn=False):
            async for msg in source:
                if msg.type == WSMsgType.TEXT:
                    data = msg.data.replace(cdn_from_text, cdn_to_text) if rewrite_cdn else msg.data
                    await destination.send_str(data)
                elif msg.type == WSMsgType.BINARY:
                    data = msg.data.replace(cdn_from_bytes, cdn_to_bytes) if rewrite_cdn else msg.data
                    await destination.send_bytes(data)
                elif msg.type == WSMsgType.PING:
                    await destination.ping(msg.data)
                elif msg.type == WSMsgType.PONG:
                    await destination.pong(msg.data)
                elif msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR):
                    break
        tasks = [asyncio.create_task(pump(downstream, upstream)),
                 asyncio.create_task(pump(upstream, downstream, rewrite_cdn=True))]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
    finally:
        await upstream.close()
        await downstream.close()
    return downstream


async def proxy(request):
    if request.path == "/health":
        return web.Response(text="ok")
    if request.path == "/__ha_auth":
        supplied = request.query.get("token", "")
        if not secrets.compare_digest(supplied, ACCESS_TOKEN):
            raise web.HTTPForbidden(text="Invalid proxy access token")
        next_path = request.query.get("next", START_PATH)
        if not next_path.startswith("/") or next_path.startswith("//"):
            next_path = START_PATH
        response = web.HTTPFound(next_path)
        secure_client = request.headers.get(
            "X-Forwarded-Proto", request.scheme
        ).lower() == "https"
        response.set_cookie(
            ROOT_AUTH_COOKIE,
            ACCESS_TOKEN,
            httponly=True,
            secure=secure_client,
            samesite="None" if secure_client else "Strict",
            path="/",
            max_age=30 * 24 * 60 * 60,
        )
        raise response
    normalized_path = re.sub(r"/{2,}", "/", request.path)
    legacy_entry = request.path.startswith("//") and normalized_path == "/protect/"
    if ingress_base(request) and normalized_path in {
        "/", "/protect", "/protect/", "/protect/dashboard"
    }:
        return embedded_wrapper()
    if normalized_path == "/" or legacy_entry:
        base = ingress_base(request)
        bootstrap = """<!doctype html><meta charset=utf-8><title>Opening Protect</title>
<style>html,body{height:100%%;margin:0;background:#f7f8fa}body{display:grid;place-items:center;font:16px system-ui;color:#556}</style>
<div>Opening UniFi Protect…</div><script>(async()=>{const B=%s;let ok=false;try{ok=(await fetch(B+'/api/users/self',{credentials:'include'})).ok}catch(e){}location.replace(B+(ok?'/protect/dashboard':'/login?redirect=%%2Fprotect%%2Fdashboard'))})()</script>""" % json.dumps(base)
        return web.Response(text=bootstrap, content_type="text/html",
                            headers={"Cache-Control": "no-store",
                                     "Content-Security-Policy": "frame-ancestors *"})
    is_cdn = request.path == CDN_PREFIX or request.path.startswith(CDN_PREFIX + "/")
    if is_cdn:
        cdn_path = request.path[len(CDN_PREFIX):] or "/"
        query = ("?" + request.query_string) if request.query_string else ""
        target = CDN_ORIGIN + cdn_path + query
    else:
        target = UPSTREAM + upstream_path(request)
    if DEBUG:
        LOG.debug("%s %s -> %s (ingress base: %s)", request.method, request.path, target,
                  ingress_base(request) or "<missing>")
    session = request.app["session"]
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return await websocket_proxy(request, session, target)
    body = await request.read()
    outgoing_headers = request_headers(request)
    if is_cdn:
        outgoing_headers["Host"] = CDN.netloc
        outgoing_headers.pop("Cookie", None)
    if DEBUG and request.path == "/api/auth/login":
        try:
            submitted = json.loads(body.decode("utf-8"))
            shape = {key: type(value).__name__ for key, value in submitted.items()}
        except Exception:
            shape = {"body": "non-JSON", "bytes": len(body)}
        safe_headers = {
            key: value for key, value in request_headers(request).items()
            if key.lower() in {"content-type", "origin", "referer", "x-forwarded-proto",
                               "x-forwarded-host", "sec-fetch-site", "sec-fetch-mode"}
        }
        outgoing = request_headers(request)
        outgoing_cookie_names = []
        if "Cookie" in outgoing:
            safe_cookie = SimpleCookie()
            safe_cookie.load(outgoing["Cookie"])
            outgoing_cookie_names = sorted(safe_cookie.keys())
        LOG.debug("UniFi login request shape=%s headers=%s upstream_cookie_names=%s", shape,
                  safe_headers, outgoing_cookie_names)
    try:
        async with session.request(request.method, target, headers=outgoing_headers, data=body,
                                   allow_redirects=False) as upstream:
            remember_upstream_cookies(request, upstream)
            base = ingress_base(request)
            secure_client = request.headers.get("X-Forwarded-Proto", request.scheme).lower() == "https"
            content_type = upstream.headers.get("Content-Type", "application/octet-stream").split(";", 1)[0].lower()
            rewritten = any(content_type.startswith(t) for t in TEXT_TYPES)
            if rewritten:
                data = await upstream.read()
                if upstream.headers.get("Content-Encoding", "").lower() == "gzip":
                    data = gzip.decompress(data)
                if request.path == "/api/auth/login" and upstream.status >= 400:
                    # The response contains only UniFi's rejection reason. Never log the
                    # submitted request body or authentication material.
                    try:
                        parsed = json.loads(data.decode("utf-8"))
                        error = parsed.get("error", parsed) if isinstance(parsed, dict) else {}
                        reason = {
                            "code": error.get("code"),
                            "message": error.get("message"),
                            "required": (error.get("data") or {}).get("required")
                            if isinstance(error.get("data"), dict) else None,
                        }
                    except Exception:
                        reason = data.decode("utf-8", errors="replace")[:500]
                    LOG.warning("UniFi login rejected with HTTP %s: %s", upstream.status, reason)
                data = rewrite_body(data, content_type, base)
                response = web.Response(status=upstream.status, body=data)
                copy_response_headers(response, upstream, base, content_type, True, secure_client)
                return response

            # Streams recordings, live media, downloads and other binary responses without buffering.
            response = web.StreamResponse(status=upstream.status)
            copy_response_headers(response, upstream, base, content_type, False, secure_client)
            await response.prepare(request)
            async for chunk in upstream.content.iter_chunked(256 * 1024):
                await response.write(chunk)
            await response.write_eof()
            return response
    except Exception as exc:
        LOG.exception("Upstream request failed: %s", target)
        return web.Response(status=502, text=f"UniFi Protect is unreachable: {exc}")


async def context(app):
    ssl_context = None
    if UP.scheme == "https":
        ssl_context = ssl.create_default_context()
        if not VERIFY_SSL:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
    connector = TCPConnector(ssl=ssl_context)
    app["session"] = ClientSession(connector=connector, timeout=ClientTimeout(total=None), auto_decompress=False)
    LOG.info("Proxying Home Assistant ingress to %s (TLS verification: %s)", UPSTREAM, VERIFY_SSL)
    if PUBLIC_ENTRY:
        LOG.info("Supervisor ingress will embed the HTTPS endpoint %s", PUBLIC_ENTRY)
    yield
    await app["session"].close()


def create_app():
    @web.middleware
    async def supervisor_only(request, handler):
        # Ingress arrives from Supervisor; root-proxy mode arrives directly from
        # the local network. Never expose the unauthenticated proxy to public IPs.
        try:
            client_ip = ipaddress.ip_address(request.remote)
        except ValueError:
            raise web.HTTPForbidden(text="Local access only")
        if not (client_ip.is_private or client_ip.is_loopback):
            raise web.HTTPForbidden(text="Local access only")
        # Supervisor ingress is already authenticated by Home Assistant. The exposed
        # root proxy requires a per-installation cookie bootstrapped by the ingress
        # wrapper so another device on the LAN cannot reuse the saved Protect session.
        if (
            not ingress_base(request)
            and request.path not in {"/health", "/__ha_auth"}
            and not secrets.compare_digest(
                request.cookies.get(ROOT_AUTH_COOKIE, ""), ACCESS_TOKEN
            )
        ):
            raise web.HTTPForbidden(text="Open Protect from the Home Assistant sidebar")
        return await handler(request)

    app = web.Application(client_max_size=4 * 1024 ** 3, middlewares=[supervisor_only])
    app["upstream_cookies"] = {}
    app["default_upstream_cookies"] = load_default_cookies()
    app.cleanup_ctx.append(context)
    app.router.add_route("*", "/{path:.*}", proxy)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=8099, access_log=LOG if DEBUG else None)
