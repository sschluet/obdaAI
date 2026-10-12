# Private Tailscale access

A dedicated VM can join the owner's tailnet while retaining its existing LAN and
reverse-proxy access. Install the client from the official signed distribution
repository, then authenticate the node in the intended Tailscale account.

The reviewed configuration uses `--accept-dns=false --accept-routes=false` so the
VM keeps its existing DNS and LAN default route. It advertises neither subnet
routes nor an exit node. Existing OpenSSH authentication remains unchanged.

For the application, use Tailscale Serve with HTTPS and the node's complete
MagicDNS name. The fixed backend is Nginx on `127.0.0.1:8777`, configured from
`deploy/nginx-tailscale.conf.template`. Replace its two placeholders with the
reviewed node hostname and existing application origin address. The listener is
loopback-only and maps only that exact HTTPS Origin to the existing application
Origin; unexpected or missing Origins remain unchanged and are rejected for
writes. Application login and CSRF checks remain required.

After checking `nginx -t`, reload Nginx and configure:

```sh
tailscale serve --bg --https=443 http://127.0.0.1:8777
tailscale serve status
```

Serve is private to the tailnet; Funnel is not enabled. Enabling HTTPS may require
an account-side confirmation presented by the Tailscale CLI. Access is also
subject to the tailnet's existing policy and any device-approval requirement.

Acceptance checks: node authenticated/online, no advertised routes/exit-node,
DNS/default route preserved, existing LAN HTTPS healthy, loopback listener not
reachable over the LAN, valid tailnet HTTPS, unauthenticated API still protected,
and authenticated writes require both the exact Origin and CSRF token. Check a
real peer connection before claiming that remote access is verified.

Before changes, retain firewall, DNS and proxy configuration snapshots privately.
Rollback the added access with `tailscale serve reset`, `tailscale down`, removal
of the dedicated Nginx configuration followed by `nginx -t` and reload. Stop or
remove the client only if removing the Tailscale installation is intended; preserve
unrelated rules and services.

References: [Linux installation](https://tailscale.com/docs/install/linux),
[Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve).


## Deployment transport

Prefer the existing LAN address. When its SSH port is unreachable, the private
deployment helper selects the registered Tailscale node address for SSH commands
and transfers. Both routes use the same deployment key and pinned host identity
with strict host-key checking. Select the transport before executing a command;
a failed deployment must not automatically run again through the alternate route.
The operator's Tailscale client must already be active in the correct tailnet.
