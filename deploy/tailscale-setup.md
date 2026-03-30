# Tailscale Mesh Network Setup

Tailscale creates a WireGuard-based mesh VPN that connects all your devices seamlessly.
This lets you SSH into the Oracle Cloud VM (or any other machine) from anywhere
without exposing ports to the public internet.

## Install on Each Machine

### Oracle Cloud VM (Ubuntu)

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
# Follow the URL to authenticate
```

### Windows

Download from https://tailscale.com/download/windows and install.

### macOS

```bash
brew install tailscale
# Or download from https://tailscale.com/download/mac
```

## Verify Connectivity

Once all devices are connected:

```bash
# From any machine
tailscale status

# SSH to the Oracle VM using Tailscale hostname
ssh ubuntu@oracle-vm  # or whatever name it appears as
```

## Useful Configuration

### Enable MagicDNS

In Tailscale admin console → DNS → enable MagicDNS.
This lets you use hostnames like `oracle-vm` instead of IP addresses.

### Disable Key Expiry (for servers)

In Tailscale admin console → Machines → click on the Oracle VM → Disable key expiry.
This prevents the VM from losing connectivity when the auth key expires.

### Exit Node (optional)

If you want to route traffic through the Oracle VM:

```bash
# On the Oracle VM
sudo tailscale up --advertise-exit-node

# On your client device
sudo tailscale up --exit-node=oracle-vm
```

## Security Notes

- Tailscale uses WireGuard encryption — all traffic between nodes is encrypted
- No ports need to be opened in Oracle Cloud security lists for Tailscale traffic
- The Tailscale admin console shows all connected devices and their status
- You can use ACLs to restrict which devices can talk to each other
