# Dugout — Oracle Cloud Infrastructure (OCI) Setup Guide

## 1. Create Oracle Cloud Account

1. Go to **[cloud.oracle.com](https://cloud.oracle.com)** and click **Sign Up**
2. Fill in your details (credit card required for verification — you will NOT be charged)
3. Choose your **Home Region** — pick the one closest to you (e.g., US East Ashburn, US West Phoenix)
4. Wait for account provisioning (usually 5-15 minutes)

## 2. Create a Free-Tier VM

1. Log in to the **OCI Console** at cloud.oracle.com
2. Click **Create a VM instance** (on the dashboard) or go to **Compute → Instances → Create Instance**

### Instance settings:

| Setting | Value |
|---|---|
| **Name** | `dugout` |
| **Compartment** | (default) |
| **Placement** | Any AD in your home region |
| **Image** | **Canonical Ubuntu 22.04** (or 24.04) — click "Change image" → Ubuntu |
| **Shape** | Click "Change shape" → **Ampere** → **VM.Standard.A1.Flex** |
| **OCPUs** | **2** (free tier allows up to 4) |
| **Memory** | **12 GB** (free tier allows up to 24) |
| **Boot volume** | 50 GB (default, free tier allows up to 200) |

### Networking:
- **VCN**: Create new or use default
- **Subnet**: Public subnet
- **Public IPv4**: **Assign a public IPv4 address** ← IMPORTANT

### SSH Key:
- Select **Paste public keys**
- Paste the contents of `infra/oracle/dugout-oci-pub.pem`:

```
(paste the PEM public key here)
```

Or use the OpenSSH format from `infra/oracle/dugout-oci.pub`.

3. Click **Create** and wait for the instance to be **Running**
4. Copy the **Public IP Address** from the instance details page

## 3. Open Port 3000 in OCI Security List

The VM's firewall AND the OCI network security list both need to allow traffic.

1. From your instance details, click the **Subnet** link
2. Click the **Default Security List**
3. Click **Add Ingress Rules**:

| Setting | Value |
|---|---|
| Source CIDR | `0.0.0.0/0` |
| IP Protocol | TCP |
| Destination Port Range | `3000` |

4. Click **Add Ingress Rules**

## 4. SSH Into the VM

```bash
ssh -i infra/oracle/dugout-oci.pem ubuntu@<PUBLIC_IP>
```

If you get a permissions error, run: `chmod 600 infra/oracle/dugout-oci.pem`

## 5. Run the Bootstrap Script

From your local machine (the Softball repo directory):

```bash
ssh -i infra/oracle/dugout-oci.pem ubuntu@<PUBLIC_IP> 'bash -s' < scripts/oci_bootstrap.sh
```

Or SSH in first, then clone and run:

```bash
ssh -i infra/oracle/dugout-oci.pem ubuntu@<PUBLIC_IP>
git clone https://github.com/anchorgroupops/Softball.git ~/dugout
cd ~/dugout
bash scripts/oci_bootstrap.sh
```

## 6. Configure Environment

```bash
ssh -i infra/oracle/dugout-oci.pem ubuntu@<PUBLIC_IP>
cd ~/dugout
nano .env
```

Fill in:
```
GC_EMAIL=fly386@gmail.com
GC_PASSWORD=<your-gamechanger-password>
GC_IMAP_APP_PASSWORD=<google-app-password-from-step-below>
GC_TEAM_ID=NuGgx6WvP7TO
GC_SEASON_SLUG=2026-spring-sharks
GC_ORG_IDS=7ZUyPJwky5DG
TEAM_SLUG=sharks
TEAM_NAME=The Sharks
LEAGUE=PCLL
DIVISION=Majors
```

Then restart:
```bash
docker compose -f docker-compose.dugout.yml up -d
```

## 7. Update Cloudflare Tunnel

Point `dugout.joelycannoli.com` to `http://<PUBLIC_IP>:3000`

## 8. Verify

```bash
curl http://<PUBLIC_IP>:3000/api/health
```

Dashboard should be accessible at `http://<PUBLIC_IP>:3000`

## Google App Password (for 2FA auto-read)

1. Go to **myaccount.google.com** → sign in as **fly386@gmail.com**
2. Search **"App passwords"** in the top search bar
3. If prompted, enable **2-Step Verification** first (Security → 2-Step Verification)
4. Create an app password named **Dugout**
5. Copy the 16-character password
6. Add to `.env`: `GC_IMAP_APP_PASSWORD=xxxx xxxx xxxx xxxx`

## Architecture on OCI

```
┌─────────────────────────────────────────────┐
│  Oracle Cloud VM (ARM, 2 OCPU, 12GB RAM)    │
│  Fixed Public IP: x.x.x.x                   │
│                                              │
│  ┌──────────────┐  ┌──────────────────────┐ │
│  │ dugout_      │  │ dugout_sync          │ │
│  │ dashboard    │  │ (Playwright scraper) │ │
│  │ :3000 (nginx)│  │ Fixed IP = no 2FA!   │ │
│  └──────┬───────┘  └──────────────────────┘ │
│         │                                    │
│  ┌──────┴───────┐                            │
│  │ dugout_api   │  ┌──────────────────────┐ │
│  │ (Flask/      │  │ watchtower           │ │
│  │  Gunicorn)   │  │ (auto-update)        │ │
│  │ :5000        │  └──────────────────────┘ │
│  └──────────────┘                            │
│                                              │
│  /home/ubuntu/dugout/data/sharks/            │
│  (persistent team data)                      │
└─────────────────────────────────────────────┘
         │
         │  Cloudflare Tunnel
         ▼
  dugout.joelycannoli.com
```

## Cost

$0. The VM.Standard.A1.Flex shape (ARM) is part of Oracle's **Always Free** tier:
- Up to 4 OCPUs and 24 GB memory total
- 200 GB boot volume
- 10 TB/month outbound data
- No time limit — free forever
