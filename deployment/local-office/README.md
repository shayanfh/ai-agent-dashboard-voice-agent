# Single-host office deployment

This installer deploys the Dashboard, Frontend, Voice Agent, LiveKit, LiveKit SIP, native
Asterisk, PostgreSQL, Redis, MinIO, Celery, and the Asterisk provisioner on one Ubuntu 24.04
server. It is intended for a New Rock HX440G/HX4G on the same trusted LAN.

## Before installation

- Use a clean Ubuntu Server 24.04 amd64 installation.
- Assign the server a static IPv4 address in Netplan before running the installer.
- Assign the New Rock a different static IPv4 address in the same subnet.
- Ensure ports `3000`, `5060`, `5062`, `7880-7882`, `8000`, `9000`, `9443`, and UDP
  `10000-29999` are not already used.
- Allow outbound HTTPS and DNS access for GitHub, container registries, OpenAI, and ElevenLabs.
- For a small office, start with at least 4 CPU cores, 8 GiB RAM, and SSD storage. More concurrent
  calls require additional CPU and bandwidth.

This is a LAN deployment. It does not configure public DNS, TLS, router port-forwarding, or a
static address in Netplan. Browser microphone test calls require HTTPS unless the browser is
running on localhost; physical PSTN calls through the New Rock do not.

## Install

```bash
git clone https://github.com/shayanfh/ai-agent-dashboard-voice-agent.git
cd ai-agent-dashboard-voice-agent
sudo bash deployment/local-office/install.sh
```

The installer asks for:

- the already-configured static server IPv4 address;
- the New Rock IPv4 address;
- the LAN subnet, for example `192.168.10.0/24`;
- one synthetic E.164 DID for the first FXO port;
- OpenAI and ElevenLabs API keys.

Secrets are generated once and stored root-only in `/etc/mozaic-office/install.env`. Application
sources and runtime files are installed under `/opt/mozaic-office`. The installer displays a
summary and requires confirmation before installing packages or changing Asterisk configuration.

The installer backs up the original Asterisk `pjsip.conf`, `extensions.conf`, and `manager.conf`,
then adds isolated include files. It does not delete existing Docker volumes or Asterisk data.

After the database migration it creates an active local company administrator and an unlimited
local subscription. The operation is idempotent and never resets the password of an existing
account:

- Email: `login@starvox.ai`
- Password: `admin@mozaic`

Change this initial password after the first login. The values can be overridden before the first
installation with `BOOTSTRAP_ADMIN_EMAIL`, `BOOTSTRAP_ADMIN_PASSWORD`, and
`BOOTSTRAP_COMPANY_NAME` environment variables.

The installer preserves a working Docker installation. If Docker CE and its `containerd.io` package
already exist, it does not try to install Ubuntu's conflicting `docker.io`/`containerd` packages.
On a host without Docker it configures Docker's official Ubuntu repository and installs Docker CE
plus the Compose plugin from the same package family.

## Service layout

| Component | Address |
|---|---|
| Frontend | `http://SERVER_IP:3000` |
| Backend | `http://SERVER_IP:8000` |
| Asterisk PJSIP | `SERVER_IP:5060/udp` |
| Asterisk RTP | `SERVER_IP:10000-19999/udp` |
| LiveKit API/WebSocket | `SERVER_IP:7880/tcp` |
| LiveKit RTC | `SERVER_IP:7881/tcp`, `SERVER_IP:7882/udp` |
| LiveKit SIP | `SERVER_IP:5062/udp` |
| LiveKit SIP RTP | `SERVER_IP:20000-29999/udp` |
| Provisioner | `SERVER_IP:9443/tcp`, authenticated |

Asterisk and LiveKit SIP use different signaling ports and RTP ranges so they can share one host.
PostgreSQL and both Redis instances are not exposed to the LAN.

## New Rock HX440G

After installation, read `/opt/mozaic-office/NEWROCK-HX440G.txt`. The baseline web UI settings are:

1. In **Basic > SIP**, set Proxy Server to `SERVER_IP:5060`, UDP transport, and local addresses in
   SIP Contact and SDP. Do not enable NAT for a same-LAN deployment.
2. In **Trunk > Feature** for the connected FXO port, disable Registration, select **Binding** for
   Inbound Handle, and set Binding Number to the DID entered during installation. If the firmware
   rejects `+`, use the same number without `+`; the generated Asterisk route accepts both.
3. Enable Caller ID detection and Echo cancellation for the FXO port.
4. Select PCMA/G.711 A-law first and PCMU/G.711 u-law second. Use RFC2833/RFC4733 DTMF.
5. In **Routing > Routing Table**, route calls received from the IP side to the desired FXO port.
   For multiple PSTN lines, use the device's round-robin FXO group.
6. In **Number transformation**, convert outbound E.164 numbers to the format accepted by the
   telephone line, typically `+98...` to `0...`.
7. If the firmware exposes an IP whitelist, permit only the Ubuntu server IP for SIP access.

Menu wording differs slightly between HX firmware versions. New Rock's documented peer setup uses
the SIP proxy field, FXO Binding Number, RFC2833, and a Routing Table entry toward the IP side.

## Create the phone number

Create an agent in the Dashboard first. Then create a Generic SIP phone number using the JSON shown
in `/opt/mozaic-office/NEWROCK-HX440G.txt` and select that agent. Press **Provision**, then place an
inbound PSTN test call.

## Operations

```bash
sudo mozaic-office status
sudo mozaic-office health
sudo mozaic-office logs 300
sudo mozaic-office restart
sudo mozaic-office bootstrap-admin
sudo mozaic-office update
```

`update` refuses to proceed if any installed repository contains local changes. It pulls only
fast-forward updates, rebuilds application images, applies Alembic migrations, and restarts the
stack. There is deliberately no automated uninstall command because database, recording, and
configuration removal must be an explicit backup-and-retention decision.

Useful diagnostics:

```bash
sudo asterisk -rvvv
pjsip show transports
pjsip show endpoints
pjsip set logger on
```

Runtime configuration is in `/opt/mozaic-office/runtime`. Installation logs are written to
`/var/log/mozaic-office-install.log`.
