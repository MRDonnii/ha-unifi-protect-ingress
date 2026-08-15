# Changelog

## 0.3.0

- Add an optional floating back button above the Protect interface.
- Allow the return destination to be any HA-root-relative path or absolute HTTP(S) URL.

## 0.2.2

- Add an original project logo and Home Assistant app icon.
- Refresh the public README with status badges, requirements and a shorter installation guide.

## 0.2.1

- Require a random per-installation cookie for the exposed root proxy.
- Restrict the Home Assistant sidebar panel to administrators.
- Keep direct LAN clients from reusing the persisted Protect session.

## 0.2.0

- Add optional embedded Cloudflare Tunnel connector with a masked tunnel-token setting.
- Add an HTTPS wrapper for the native HA sidebar so Protect keeps its root-relative routes.
- Add an automatic LAN/VPN wrapper that derives the local proxy host from the HA URL.
- Keep LAN-only root proxy mode for installations that do not use HTTPS.

## 0.1.0

- Initial experimental release.
- Home Assistant sidebar and Supervisor ingress support.
- Dynamic subpath rewriting for UniFi OS Protect resources.
- HTTP, WebSocket, cookie, redirect, CSP and frame-header proxy handling.
- Streaming proxy for recordings and other binary media.
