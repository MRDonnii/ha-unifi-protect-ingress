# UniFi Protect Ingress for Home Assistant

[![Open in Home Assistant](https://my.home-assistant.io/badges/supervisor_addon.svg)](https://my.home-assistant.io/redirect/supervisor_addon_store/?repository_url=https%3A%2F%2Fgithub.com%2FMRDonnii%2Fha-unifi-protect-ingress)

Experimental Home Assistant app/add-on that places the native UniFi Protect interface in the
Home Assistant sidebar. It is based on the ingress pattern used by Frigate Proxy, with extra
handling required by UniFi OS applications that assume they run at the web-server root.

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

## Install from GitHub (Home Assistant OS or Supervised)

After this folder has been published as the public repository
`https://github.com/MRDonnii/ha-unifi-protect-ingress` and its first GitHub Actions build has
completed:

1. Click **Open in Home Assistant** above, or open **Settings -> Apps -> App store -> Repositories**.
2. Add `https://github.com/MRDonnii/ha-unifi-protect-ingress`.
3. Select **UniFi Protect Ingress**, install it, and set `protect_url`.
4. Start the app and enable **Show in sidebar**.

If installation reports `401 Unauthorized` while downloading the image, open the package on the
GitHub repository's **Packages** page, choose **Package settings -> Change visibility**, and make
the container package public.

## Publish this repository

1. Create a public, empty GitHub repository named `ha-unifi-protect-ingress` under `MRDonnii`.
2. Push the contents of this directory to its `main` branch.
3. Open the repository's **Actions** page. The lint workflow validates the app and runs unit tests;
   the build workflow creates and publishes all declared CPU architectures to GitHub Container
   Registry.
4. Make the resulting `ha-unifi-protect-ingress` container package public if GitHub did not do so
   automatically.
5. Test the Home Assistant installation link above before announcing the repository.

The `version` in `unifi_protect_ingress/config.yaml` is both the add-on version and published
container tag. Increase it for every released change and document the release in `CHANGELOG.md`.

## Install locally before the first GitHub build

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
```

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
