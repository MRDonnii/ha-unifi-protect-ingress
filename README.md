<p align="center">
  <img src="unifi_protect_ingress/logo.png" width="180" alt="UniFi Protect Ingress logo">
</p>

<h1 align="center">UniFi Protect Ingress for Home Assistant</h1>

<p align="center">
  The native UniFi Protect web interface, embedded securely in the Home Assistant sidebar.
</p>

<p align="center">
  <a href="https://my.home-assistant.io/redirect/supervisor_addon_store/?repository_url=https%3A%2F%2Fgithub.com%2FMRDonnii%2Fha-unifi-protect-ingress"><img src="https://my.home-assistant.io/badges/supervisor_addon.svg" alt="Open in Home Assistant"></a>
</p>

<p align="center">
  <a href="https://github.com/MRDonnii/ha-unifi-protect-ingress/actions/workflows/lint.yaml"><img src="https://github.com/MRDonnii/ha-unifi-protect-ingress/actions/workflows/lint.yaml/badge.svg" alt="Lint status"></a>
  <a href="https://github.com/MRDonnii/ha-unifi-protect-ingress/actions/workflows/builder.yaml"><img src="https://github.com/MRDonnii/ha-unifi-protect-ingress/actions/workflows/builder.yaml/badge.svg" alt="Build status"></a>
  <a href="https://github.com/MRDonnii/ha-unifi-protect-ingress/releases/latest"><img src="https://img.shields.io/github/v/release/MRDonnii/ha-unifi-protect-ingress" alt="Latest release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/MRDonnii/ha-unifi-protect-ingress" alt="MIT license"></a>
</p>

This experimental Home Assistant app/add-on follows the ingress pattern used by Frigate Proxy,
with additional handling for UniFi OS applications that expect to run at the web-server root.

## Requirements

- Home Assistant OS or Home Assistant Supervised
- A UniFi console running Protect, reachable from Home Assistant over the LAN
- A 64-bit Intel/AMD or ARM Home Assistant host
- A local UniFi OS account is recommended; credentials are entered directly into UniFi and are
  never stored in this app's configuration

## What it handles

- Home Assistant ingress authentication and dynamic `X-Ingress-Path`
- HTTP and WebSocket proxying (`/proxy/protect`, `/api/ws`, `/wss`)
- streaming of recordings and other binary responses without buffering the whole file
- rewrite of absolute paths in HTML, JavaScript, CSS and JSON
- runtime rewriting for `fetch`, `XMLHttpRequest` and `WebSocket`
- `Location` redirects and upstream cookie `Path`/`Domain`
- self-signed UniFi certificates
- removal/replacement of upstream CSP and `X-Frame-Options` frame restrictions
- `Origin`, `Referer`, `Host` and forwarded headers expected by UniFi OS
- optional Cloudflare Tunnel connector for a proper HTTPS origin in the HA mobile app
- an ingress wrapper that embeds the HTTPS endpoint without rewriting Protect's SPA routes
- automatic local embedding through the current HA hostname and port 8099 when no public URL is set
- per-installation root-proxy authorization and an administrator-only HA panel
- an optional floating back button with a configurable Home Assistant destination

## Quick installation

1. Click **Open in Home Assistant** above, or open **Settings -> Apps -> App store -> Repositories**.
2. Add `https://github.com/MRDonnii/ha-unifi-protect-ingress`.
3. Select **UniFi Protect Ingress** and install it.
4. Set `protect_url` to the console's direct LAN URL, for example `https://192.168.1.1`.
5. Start the app, enable **Show in sidebar**, and sign in to UniFi Protect.

The prebuilt container is public, so no GitHub account or registry login is required.

## Local development installation

1. Copy the `unifi_protect_ingress` directory into `/addons/unifi_protect_ingress` on the Home
   Assistant machine. The Studio Code Server, Samba share or Terminal/SSH app can do this.
2. In **Settings -> Apps -> App store**, open the menu and choose **Check for updates**.
3. Open **Local apps**, select **UniFi Protect Ingress**, then install it.
4. Temporarily remove the `image:` line from `config.yaml` so Supervisor builds the Dockerfile
   locally, then install the app.
5. Set `protect_url` to the console's direct LAN URL, for example `https://192.168.1.1`.
6. Leave `verify_ssl: false` for the usual self-signed UniFi certificate.
7. Start the app and enable **Show in sidebar**. Open **Protect** from the sidebar and sign in.

### HTTPS / Home Assistant mobile app

When Home Assistant itself is opened over HTTPS, browsers will block an HTTP Protect iframe. For
that case, create a dedicated remotely-managed Cloudflare Tunnel and add one published application:

1. Choose a hostname, for example `protect.example.com`.
2. Set its service to `http://localhost:8099`.
3. Copy the tunnel token from **Add a replica** into `cloudflare_tunnel_token`.
4. Set `public_url` to `https://protect.example.com`.
5. Restart the app and enable its native **Show in sidebar** switch.

The token is stored as a masked Home Assistant app option and written to a mode-0600 token file.
It can run only that tunnel; it cannot create DNS records or manage the Cloudflare account. The
hostname-to-service route must therefore be created once in Cloudflare. If an existing Cloudflared
instance is used instead, leave `cloudflare_tunnel_token` empty and route the hostname to
`http://HOME_ASSISTANT_LAN_IP:8099`.

### LAN/VPN mode

Leave both Cloudflare fields empty and open Home Assistant through its local HTTP address. The
native add-on sidebar panel automatically embeds
`http://CURRENT_HOME_ASSISTANT_HOST:8099/protect/`; no `panel_iframe` YAML is required. The same
address works remotely when the device is connected to a VPN that can reach the HA LAN address.
Port 8099 rejects direct requests until the HA ingress wrapper has issued that browser the
installation-specific access cookie.

## Default configuration

```yaml
protect_url: https://192.168.1.1
verify_ssl: false
start_path: /protect/
rewrite_paths:
  - /proxy/protect
  - /api/ws
  - /wss
  - /protect
debug: false
public_url: ""
cloudflare_tunnel_token: ""
back_button_enabled: false
back_button_target: "/"
```

### Optional back button

Enable `back_button_enabled` to show a floating arrow above Protect. Set
`back_button_target` to an HA path such as `/lovelace/home` or `/dashboard-camera/0`. A complete
`http://` or `https://` Home Assistant URL is also accepted when the destination uses another
hostname. The default `/` returns to the Home Assistant root page.

If a browser error shows another root-relative UniFi path, add that path to `rewrite_paths`, turn
on `debug`, restart, and reload the sidebar page without cache.

## Validation

Run the path, redirect and cookie unit tests from this repository with:

```sh
python -m unittest discover -s tests -v
```

Live end-to-end validation still requires the target UniFi console and Home Assistant Supervisor,
because the ingress prefix is session-specific and Protect firmware bundles differ by release.

## Limitations

- This is intentionally marked `experimental`. UniFi does not officially support hosting the full
  Protect SPA below an arbitrary subpath and can change internal paths between releases.
- A recent UniFi OS release may enforce strict WebSocket Origin validation. This proxy rewrites
  Origin to the console origin, but console-side policy can still reject it.
- Home Assistant Container/Core installations do not have Supervisor ingress and cannot install
  this app. Use HA OS/Supervised, or the fallback NGINX configuration in `nginx-fallback.conf` with
  a `panel_iframe` entry.
- Cloudflare setup is optional. Without `public_url`, port 8099 is LAN-only and cannot be embedded
  by an HTTPS Home Assistant session because browsers prohibit mixed content.
