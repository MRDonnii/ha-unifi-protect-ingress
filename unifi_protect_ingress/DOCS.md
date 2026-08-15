# UniFi Protect Ingress

Set **UniFi console URL** to the direct address Home Assistant can reach, such as
`https://192.168.1.1`. Start the app, enable **Show in sidebar**, and open **Protect**.

The default start path and rewrite paths fit current UniFi OS Protect installations. Enable debug
logging only while troubleshooting. If the log reports TLS verification errors with a self-signed
console certificate, turn **Verify the console certificate** off.

This app proxies the real Protect interface; it does not replace Home Assistant's official UniFi
Protect integration for camera entities, events and automations.

## Optional back button

Turn on **Show back button** to place a floating arrow in the upper-left corner of Protect. Set
**Back button HA destination** to the page it should open. Examples:

- `/` for the Home Assistant start page
- `/lovelace/home` for a Lovelace view
- `/dashboard-camera/0` for a custom camera dashboard
- `https://ha.example.com/dashboard/0` when a complete HA address is required

Paths without a leading slash are automatically treated as Home Assistant paths. The button is
drawn by the ingress wrapper and therefore remains available while navigating between Protect
pages.

## Cloudflare/HTTPS mode

Use this mode when Home Assistant is opened through an HTTPS URL or the Companion App:

1. In Cloudflare, create a dedicated remotely-managed tunnel.
2. Add a published application such as `protect.example.com` with service
   `http://localhost:8099`.
3. Open **Add a replica** and copy only the tunnel token into **Cloudflare Tunnel token**.
4. Set **Public HTTPS URL** to `https://protect.example.com`.
5. Restart this app. Its normal Home Assistant sidebar entry now embeds the HTTPS endpoint.

Do not use a Global API key. The tunnel token is intentionally narrower: it can run the selected
tunnel but cannot change DNS, zones or other tunnels. If Cloudflared already runs elsewhere, leave
the token empty and point the published application at this Home Assistant host's port 8099.
