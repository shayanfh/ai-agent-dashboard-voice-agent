# Central FreePBX gateway: complete FreePBX 17 setup

This is the complete one-time installation guide for the shared FreePBX gateway. All customer
calls use this path:

```text
Twilio or generic SIP provider
              |
              v
          Central FreePBX
              |
              v
          LiveKit SIP
              |
              v
           Voice Agent
              |
              v
       Dashboard Backend
```

The Dashboard Backend calls the private Asterisk provisioner API. The provisioner creates and
removes isolated PJSIP and dialplan sections for each customer and reloads Asterisk through AMI.
Asterisk records every routed call with `MixMonitor` and uploads the WAV file to the Backend.
LiveKit Egress is not used.

## Server placement

These are separate servers. Do not run the Voice Agent container on the FreePBX server:

| Server | Runs here |
|---|---|
| FreePBX server | FreePBX/Asterisk, provisioner, generated PJSIP/dialplan, MixMonitor uploader |
| Voice Agent server | Voice Agent repository and `voice-agent` container |
| LiveKit server | LiveKit Server and LiveKit SIP |
| Backend server | FastAPI Backend, database, Redis, object storage |

Only the repository's `deployment/asterisk` directory must be copied to the FreePBX server. It is
source/configuration for building the provisioner; copying it does not run the Voice Agent there.

On the FreePBX server, create its deployment directory:

```bash
sudo install -d -o root -g root -m 0755 /opt/ai-agent-freepbx
```

From the Voice Agent server or deployment workstation, copy this directory to FreePBX:

```bash
cd /path/to/ai-agent-dashboard-voice-agent
rsync -av deployment/asterisk/ \
  root@FREEPBX_PRIVATE_IP:/opt/ai-agent-freepbx/
```

If the repository is private and cloning it on FreePBX is easier, cloning the full repository is
also acceptable, but only `deployment/asterisk` is used on that server. Never start the root Voice
Agent `docker-compose.yml` on FreePBX.

## 1. Required information

Collect these values before starting:

| Value | Example |
|---|---|
| FreePBX public IP | `203.0.113.20` |
| FreePBX private IP | `10.0.1.20` |
| Optional SIP domain | `sip.example.com` |
| LiveKit SIP hostname | `project-name.sip.livekit.cloud` |
| Dashboard Backend URL | `https://api.example.com` |
| Backend `INTERNAL_API_KEY` | a long random secret |
| Provisioner API key | another long random secret |
| Asterisk AMI secret | another long random secret |

For UDP, a domain is optional. `PUBLIC_IP:5060` can be used directly. A valid domain and matching
certificate are required when TLS is enabled later.

Generate independent secrets:

```bash
openssl rand -hex 32
openssl rand -hex 32
```

Do not reuse the Backend internal key as the provisioner or AMI key.

## 2. FreePBX networking

Open **Settings -> Asterisk SIP Settings** in FreePBX and verify:

- `External Address` is the public IP of the FreePBX server.
- `Local Networks` contains every private network used by FreePBX and Docker.
- The PJSIP UDP transport is enabled on port `5060`.
- The RTP range is configured; FreePBX commonly uses UDP `10000-20000`.

Apply the FreePBX configuration, then inspect the real transport identifiers:

```bash
sudo fwconsole reload
sudo asterisk -rx "pjsip show transports"
```

The currently tested FreePBX output is:

```text
Transport:  0.0.0.0-udp  udp  0.0.0.0:5060
```

With that output, use only UDP until TCP or TLS is explicitly enabled in FreePBX. Do not create a
second transport on port 5060 and do not edit these generated files:

```text
/etc/asterisk/pjsip.conf
/etc/asterisk/pjsip.transports.conf
/etc/asterisk/pjsip.endpoint.conf
/etc/asterisk/pjsip.registration.conf
```

## 3. Firewall and NAT

Allow the following traffic:

| Direction | Port | Source/destination | Purpose |
|---|---:|---|---|
| inbound | UDP 5060 | configured SIP providers | SIP signaling |
| inbound | UDP 10000-20000 | configured provider media ranges | RTP audio |
| outbound | UDP 5060 | LiveKit SIP | SIP signaling |
| outbound | UDP/RTP | LiveKit media ranges | RTP audio |
| inbound | TCP 9443 | Backend private IP only | Provisioner API |
| local only | TCP 5038 | `127.0.0.1` only | Asterisk AMI |

Use the current official Twilio and LiveKit networking documentation for their IP/CIDR ranges.
Do not expose AMI to the internet. Keep port 9443 on a private network/VPN or behind an internal
TLS reverse proxy. Restrict SIP/RTP to provider ranges whenever the provider publishes them.

If the server is behind NAT, forward SIP and RTP to the FreePBX private IP and ensure the
FreePBX External Address is still the public IP.

## 4. Create protected generated-config files

SSH into the **FreePBX server** and run:

```bash
sudo install -d -o root -g asterisk -m 2770 /etc/asterisk/ai-agent-generated
sudo install -o root -g asterisk -m 0640 /dev/null \
  /etc/asterisk/ai-agent-generated/pjsip.conf
sudo install -o root -g asterisk -m 0640 /dev/null \
  /etc/asterisk/ai-agent-generated/extensions.conf
```

Find the numeric Asterisk group ID; it is needed by Docker:

```bash
getent group asterisk
```

Example output:

```text
asterisk:x:1001:
```

In this example, `ASTERISK_GID` is `1001`.

## 5. Add FreePBX-safe includes

The main `pjsip.conf` is generated by FreePBX and already contains:

```ini
#include pjsip_custom.conf
```

Edit the custom file:

```bash
sudo editor /etc/asterisk/pjsip_custom.conf
```

Add this line once:

```ini
#include ai-agent-generated/pjsip.conf
```

Now edit the FreePBX custom dialplan file:

```bash
sudo editor /etc/asterisk/extensions_custom.conf
```

Add this line once:

```ini
#include ai-agent-generated/extensions.conf
```

The same two lines are available in
`provisioner/freepbx-custom-includes.conf.example` for reference.

Verify there is exactly one copy of each include:

```bash
grep -n "ai-agent-generated" /etc/asterisk/pjsip_custom.conf
grep -n "ai-agent-generated" /etc/asterisk/extensions_custom.conf
```

The generated files are empty at this stage, so reloading is safe:

```bash
sudo fwconsole reload
```

## 6. Configure the localhost-only AMI account

FreePBX normally includes `/etc/asterisk/manager_custom.conf`. Edit it without replacing any
existing content:

```bash
sudo editor /etc/asterisk/manager_custom.conf
```

Add this section and replace the secret:

```ini
[ai-provisioner]
secret=REPLACE_WITH_LONG_AMI_SECRET
deny=0.0.0.0/0.0.0.0
permit=127.0.0.1/255.255.255.255
read=system,command
write=system,command
writetimeout=5000
```

The same section is available in `provisioner/freepbx-manager-custom.conf.example`.

Reload and verify AMI:

```bash
sudo asterisk -rx "manager reload"
sudo asterisk -rx "manager show user ai-provisioner"
```

The user must show localhost permission and `system,command` privileges.

## 7. Install Asterisk recording upload

The generated dialplan uses `MixMonitor`. Install the protected recording directory, uploader,
retry script, and configuration:

```bash
cd /opt/ai-agent-freepbx
sudo install -d -o asterisk -g asterisk -m 0750 \
  /var/spool/asterisk/monitor/ai-agent
sudo install -o root -g root -m 0755 upload-asterisk-recording.sh \
  /usr/local/bin/upload-asterisk-recording.sh
sudo install -o root -g root -m 0755 retry-pending-asterisk-recordings.sh \
  /usr/local/bin/retry-pending-asterisk-recordings.sh
sudo install -o root -g asterisk -m 0640 ai-agent-recording.conf.example \
  /etc/asterisk/ai-agent-recording.conf
sudo editor /etc/asterisk/ai-agent-recording.conf
```

Set the real Backend values:

```dotenv
DASHBOARD_BACKEND_URL=https://api.example.com
DASHBOARD_INTERNAL_API_KEY=<same-as-backend-INTERNAL_API_KEY>
DELETE_AFTER_UPLOAD=false
```

The URL must not contain `/api/v1` and must not end with `/`. Keep
`DELETE_AFTER_UPLOAD=false` until uploads and playback have been verified.

Add a root cron entry with `sudo crontab -e`:

```cron
*/5 * * * * /usr/local/bin/retry-pending-asterisk-recordings.sh >> /var/log/asterisk/recording-upload.log 2>&1
```

## 8. Configure the Asterisk provisioner

Docker and Docker Compose must be installed on the FreePBX server. Then:

```bash
cd /opt/ai-agent-freepbx/provisioner
cp .env.example .env
sudo editor .env
```

For the currently available FreePBX UDP transport, use this configuration:

```dotenv
PROVISIONER_API_KEY=<long-provisioner-api-key>

PUBLIC_SIP_URI=sip:ASTERISK_PUBLIC_IP_OR_DOMAIN:5060;transport=udp
LIVEKIT_SIP_URI=sip:YOUR_LIVEKIT_SIP_HOST:5060;transport=udp
LIVEKIT_AUTH_USERNAME=
LIVEKIT_AUTH_PASSWORD=

LIVEKIT_TRANSPORT_NAME=0.0.0.0-udp
PJSIP_UDP_TRANSPORT_NAME=0.0.0.0-udp
PJSIP_TCP_TRANSPORT_NAME=0.0.0.0-tcp
PJSIP_TLS_TRANSPORT_NAME=0.0.0.0-tls

# Required before provisioning any Twilio connection. Use Twilio's current official CIDRs.
TWILIO_SIGNALING_CIDRS=

AMI_HOST=127.0.0.1
AMI_PORT=5038
AMI_USERNAME=ai-provisioner
AMI_PASSWORD=<same-secret-from-manager_custom.conf>
AMI_TIMEOUT_SECONDS=10

ENABLE_RECORDING=true
RECORDING_DIRECTORY=/var/spool/asterisk/monitor/ai-agent
RECORDING_UPLOADER=/usr/local/bin/upload-asterisk-recording.sh

ASTERISK_GID=<numeric-asterisk-group-id>
STATE_FILE=/var/lib/asterisk-provisioner/connections.json
GENERATED_PJSIP_FILE=/etc/asterisk/ai-agent-generated/pjsip.conf
GENERATED_DIALPLAN_FILE=/etc/asterisk/ai-agent-generated/extensions.conf
```

Only the UDP name currently exists in FreePBX. The TCP/TLS names are placeholders for future
FreePBX transports. Customer connections must select `transport: "udp"` until those transports
are enabled and their exact IDs are copied from `pjsip show transports`.

Start the provisioner:

```bash
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 asterisk-provisioner
```

Test its authenticated health endpoint, replacing the key directly:

```bash
curl --fail \
  -H "X-Provisioner-API-Key: REPLACE_WITH_PROVISIONER_API_KEY" \
  http://127.0.0.1:9443/health
```

Expected response:

```json
{"status":"ok"}
```

## 9. Configure the Dashboard Backend

Run this section on the **Backend server**, not FreePBX.

Set these values in the Backend `.env`:

```dotenv
ASTERISK_PROVISIONER_URL=http://ASTERISK_PRIVATE_IP:9443
ASTERISK_PROVISIONER_API_KEY=<same-as-PROVISIONER_API_KEY>
ASTERISK_PUBLIC_SIP_URI=sip:ASTERISK_PUBLIC_IP_OR_DOMAIN:5060;transport=udp
ASTERISK_REQUEST_TIMEOUT_SECONDS=15
```

The Backend must reach port 9443 through the private network. Apply the migration and restart:

```bash
cd /path/to/ai-agent-dashboard
docker compose exec api alembic upgrade head
docker compose up -d --build api
docker compose logs --tail=100 api
```

The Alembic head for this feature is `0007_asterisk_gateway`.

## 10. Create the one central LiveKit trunk

Run this section on the **Voice Agent/deployment server** where the `lk` CLI is authenticated to
your LiveKit project. Do not run it inside FreePBX.

Edit `deployment/livekit/inbound-trunk.example.json` and replace:

```text
ASTERISK_PUBLIC_IP/32
```

with the real Asterisk public IP/CIDR. Keep `numbers` empty because this single protected trunk
receives all customer DIDs forwarded by Asterisk:

```json
"numbers": []
```

Create the trunk and dispatch rule once:

```bash
cd /path/to/ai-agent-dashboard-voice-agent
lk sip inbound create deployment/livekit/inbound-trunk.example.json
lk sip dispatch create deployment/livekit/dispatch-rule.example.json \
  --trunks SIP_TRUNK_ID_RETURNED_ABOVE
```

Do not create one LiveKit trunk per customer. The dispatch `agentName` must remain
`ai-agent-dashboard-inbound`, matching the Voice Agent `LIVEKIT_AGENT_NAME`.

LiveKit Cloud requires `allowedAddresses` to be enabled for the project. If that feature is not
available, configure `authUsername`/`authPassword` on the LiveKit inbound trunk and put the same
values in `LIVEKIT_AUTH_USERNAME`/`LIVEKIT_AUTH_PASSWORD` before provisioning calls.

## 11. Configure and run the Voice Agent

Run this section only on the separate **Voice Agent server**.

In the Voice Agent `.env`, configure the normal LiveKit and Backend values and enable Asterisk
recording correlation:

```dotenv
LIVEKIT_URL=wss://YOUR_LIVEKIT_HOST
LIVEKIT_API_KEY=<livekit-api-key>
LIVEKIT_API_SECRET=<livekit-api-secret>
LIVEKIT_AGENT_NAME=ai-agent-dashboard-inbound

DASHBOARD_BACKEND_URL=https://api.example.com
DASHBOARD_INTERNAL_API_KEY=<same-as-backend-INTERNAL_API_KEY>

ENABLE_CALL_RECORDING=true
ASTERISK_LINKED_ID_WAIT_SECONDS=2
```

Start it using the project's normal deployment method:

```bash
cd /path/to/ai-agent-dashboard-voice-agent
docker compose up -d --build
docker compose logs --tail=100 voice-agent
```

## 12. Provision the first customer connection

### Generic SIP with provider registration

Use this when the provider gives the customer a registrar, username, and password:

```json
{
  "name": "Customer SIP registration",
  "provider": "generic_sip",
  "phone_number": "+19714361744",
  "agent_id": "AGENT_UUID",
  "sip": {
    "mode": "registration",
    "server_uri": "sip:provider.example.com",
    "server_port": 5060,
    "auth_username": "provider-username",
    "auth_password": "provider-password-at-least-12-chars",
    "transport": "udp"
  }
}
```

### Generic SIP with IP trunk

Use this when the customer must set the destination in the provider panel:

```json
{
  "name": "Customer IP trunk",
  "provider": "generic_sip",
  "phone_number": "+19714361744",
  "agent_id": "AGENT_UUID",
  "sip": {
    "mode": "ip_trunk",
    "allowed_addresses": ["PROVIDER_SIGNALING_IP/32"],
    "transport": "udp"
  }
}
```

Call `POST /api/v1/phone-connections/{id}/provision` after creation. For `ip_trunk`, copy the
returned `provider_setup.destination_sip_uri` into the provider panel. Twilio provisioning sets
the Origination URI automatically.

## 13. End-to-end verification

After provisioning at least one number, run on the FreePBX server:

```bash
sudo asterisk -rx "pjsip show transports"
sudo asterisk -rx "pjsip show endpoint ai-livekit"
sudo asterisk -rx "pjsip show endpoints"
sudo asterisk -rx "pjsip show registrations"
sudo asterisk -rx "dialplan show ai-agent-provider-inbound"
sudo asterisk -rx "dialplan show ai-agent-forward"
docker compose -f /opt/ai-agent-freepbx/provisioner/docker-compose.yml \
  logs --tail=100 asterisk-provisioner
```

Place an inbound test call and verify:

1. The provider sends the DID to Asterisk.
2. Asterisk enters `ai-agent-provider-inbound` and forwards the DID to `ai-livekit`.
3. LiveKit creates a `call-...` room and dispatches the Voice Agent.
4. The Backend creates the Call record and stores messages.
5. Asterisk creates a WAV under `/var/spool/asterisk/monitor/ai-agent`.
6. The uploader attaches the WAV to the Call and the Dashboard recording URL works.

Useful live diagnostics:

```bash
sudo asterisk -rvvvvv
pjsip set logger on
```

Disable SIP logging after the test because it may contain phone numbers and SIP metadata:

```text
pjsip set logger off
```

## 14. Common failures

### Provisioner returns `502 Bad Gateway`

The Backend reached and authenticated to the provisioner, but config rendering, file writing, or
the AMI reload failed. Rebuild the current provisioner and inspect the exception immediately after
retrying the connection:

```bash
cd /opt/ai-agent-freepbx/provisioner
docker compose up -d --build
docker compose logs -f asterisk-provisioner
```

Test AMI from inside the container:

```bash
docker compose exec asterisk-provisioner python -c \
  "import asyncio; from app.ami import AmiClient; from app.config import settings; print(asyncio.run(AmiClient(settings).command('core show version')))"
```

Also verify generated-file access:

```bash
docker compose exec asterisk-provisioner id
docker compose exec asterisk-provisioner sh -c \
  'test -w /etc/asterisk/ai-agent-generated && echo writable'
sudo asterisk -rx "manager show user ai-provisioner"
```

For a Twilio connection, `TWILIO_SIGNALING_CIDRS` must be populated before provisioning. The new
exception log states the exact missing setting or AMI/config error.

### `Invalid HTTP request received` on port 9443

The provisioner itself serves plain HTTP. Use this URL on a private network:

```dotenv
ASTERISK_PROVISIONER_URL=http://FREEPBX_PRIVATE_IP:9443
```

Do not use `https://` unless an internal TLS reverse proxy is actually installed in front of the
container. Firewall TCP 9443 so only the Backend private IP can reach it; random public scans and
TLS requests against the plain HTTP port produce this warning.

### `Unable to retrieve PJSIP transport 0.0.0.0-udp`

The value in `PJSIP_UDP_TRANSPORT_NAME` does not match `pjsip show transports` exactly, or the
FreePBX UDP transport is disabled.

### Provisioner cannot write generated config

Check ownership, mode, and Docker group ID:

```bash
ls -ld /etc/asterisk/ai-agent-generated
ls -l /etc/asterisk/ai-agent-generated
getent group asterisk
grep '^ASTERISK_GID=' /opt/ai-agent-freepbx/provisioner/.env
```

The directory should be `root:asterisk` with mode `2770`.

### Provisioner cannot connect to AMI

```bash
sudo asterisk -rx "manager show user ai-provisioner"
ss -lntp | grep 5038
docker compose logs --tail=100 asterisk-provisioner
```

`AMI_HOST` must remain `127.0.0.1` because the container uses host networking.

### SIP connects but there is no audio

Recheck External Address, Local Networks, RTP port forwarding/firewall, provider media CIDRs, and
the allowed codecs. The generated endpoints currently allow `ulaw,alaw`.

### Recording exists locally but is missing from the Dashboard

```bash
ls -la /var/spool/asterisk/monitor/ai-agent
sudo tail -n 100 /var/log/asterisk/recording-upload.log
sudo -u asterisk /usr/local/bin/retry-pending-asterisk-recordings.sh
```

Confirm that `/etc/asterisk/ai-agent-recording.conf` contains the correct Backend URL and internal
API key and is readable by the `asterisk` group.

## 15. Provisioner tests

```bash
cd /opt/ai-agent-freepbx/provisioner
python -m pip install -r requirements-dev.txt
pytest -q
```
