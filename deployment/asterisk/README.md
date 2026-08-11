# Central Asterisk gateway

All customer calls use this path:

`Twilio or generic SIP provider -> central Asterisk -> LiveKit SIP -> Voice Agent`

The Backend calls the private provisioner API in `provisioner/`. It writes isolated PJSIP and
dialplan sections, reloads Asterisk through AMI, reports registration health, and removes the
sections when a phone connection is disconnected or deleted.

Supported customer modes:

- `twilio`: the Backend configures Twilio's Origination URI and the provisioner allows the
  administrator-managed Twilio signaling CIDRs.
- `generic_sip / registration`: the provisioner creates the PJSIP auth, AOR, endpoint, and
  outbound registration automatically.
- `generic_sip / ip_trunk`: the provisioner creates endpoint identification and routing. The
  response tells the customer which Asterisk destination URI to enter in the provider panel.

## One-time Asterisk setup

1. Copy the transport definitions from `provisioner/pjsip-transports.conf.example` into
   `/etc/asterisk/pjsip.conf` and replace public address, local network, and TLS certificate paths.
   Transport changes require an Asterisk restart.
2. Add both `#include` lines from `provisioner/asterisk-includes.conf.example` to the corresponding
   Asterisk config files. With FreePBX, use supported custom include files and never edit generated
   FreePBX files.
3. Install `provisioner/manager.conf.example` as an AMI user under `/etc/asterisk/manager.d/`, set
   a strong secret, and keep AMI bound/permitted only on localhost.
4. Create the generated config directory with an Asterisk-readable setgid group:

```bash
sudo install -d -o root -g asterisk -m 2770 /etc/asterisk/ai-agent-generated
sudo install -o root -g asterisk -m 0640 /dev/null /etc/asterisk/ai-agent-generated/pjsip.conf
sudo install -o root -g asterisk -m 0640 /dev/null /etc/asterisk/ai-agent-generated/extensions.conf
getent group asterisk
```

Put the numeric group ID in `provisioner/.env` as `ASTERISK_GID`. The provisioner runs as UID
10001; generated config is mode `0640`, state and credentials remain mode `0600`.

## Provisioner deployment

```bash
cd deployment/asterisk/provisioner
cp .env.example .env
editor .env
docker compose up -d --build
docker compose logs -f asterisk-provisioner
```

Set `TWILIO_SIGNALING_CIDRS` from Twilio's current official networking documentation. Do not copy
an old IP list into application code. `PUBLIC_SIP_URI` is the TLS SIP URI customers/providers can
reach. `LIVEKIT_SIP_URI` is the central LiveKit SIP endpoint.

The API listens on port 9443 with API-key authentication but the container itself serves plain
HTTP. Expose it only over a private network/VPN and firewall it to the Backend, or put an internal
TLS reverse proxy in front of it. Never expose AMI or the provisioner directly to the public
internet. Set these Backend values to the corresponding private/TLS endpoint:

```dotenv
ASTERISK_PROVISIONER_URL=http://ASTERISK_PRIVATE_IP:9443
ASTERISK_PROVISIONER_API_KEY=<same-as-PROVISIONER_API_KEY>
ASTERISK_PUBLIC_SIP_URI=sip:sip.example.com:5061;transport=tls
```

Validate before provisioning customer numbers:

```bash
curl -H "X-Provisioner-API-Key: $PROVISIONER_API_KEY" http://127.0.0.1:9443/health
sudo asterisk -rx "manager show user ai-provisioner"
sudo asterisk -rx "pjsip show transports"
sudo asterisk -rx "pjsip show endpoint ai-livekit"
```

Then create the one central LiveKit inbound trunk and dispatch rule from `deployment/livekit`.

## Recording

The generated dialplan uses `MixMonitor` when `ENABLE_RECORDING=true`. Install the uploader and
protected recording directory:

```bash
sudo install -d -o asterisk -g asterisk -m 0750 /var/spool/asterisk/monitor/ai-agent
sudo install -o root -g root -m 0755 upload-asterisk-recording.sh /usr/local/bin/upload-asterisk-recording.sh
sudo install -o root -g root -m 0755 retry-pending-asterisk-recordings.sh /usr/local/bin/retry-pending-asterisk-recordings.sh
sudo install -o root -g asterisk -m 0640 ai-agent-recording.conf.example /etc/asterisk/ai-agent-recording.conf
```

Keep `DELETE_AFTER_UPLOAD=false` until uploads have been verified. Retry failed uploads every five
minutes, then apply a separate retention policy to old local recordings:

```cron
*/5 * * * * /usr/local/bin/retry-pending-asterisk-recordings.sh >> /var/log/asterisk/recording-upload.log 2>&1
```

## Provisioner tests

```bash
cd deployment/asterisk/provisioner
python -m pip install -r requirements-dev.txt
pytest -q
```
