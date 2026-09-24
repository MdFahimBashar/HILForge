# Windows host agent

The host agent runs directly on a Windows laptop as a normal user process. It
uses the same PulseHunter registration, heartbeat, and job-execution HTTP
contract as the simulators, but performs predefined checks of its own machine.
It does not execute commands sent by the server. The laptop and desktop must
be on a trusted LAN; this MVP has no agent authentication or TLS.

## Desktop setup

From a checkout containing the host-agent milestone, open PowerShell in the
repository root. The API normally binds to localhost. For this trusted-LAN
test, temporarily publish it on the desktop's LAN interface:

```powershell
$env:PULSEHUNTER_API_BIND = '0.0.0.0'
docker compose up --build --detach --wait
```

Confirm the laptop can reach `http://192.168.30.198:8000/health`. Replace the
example IP if the desktop address changes. Do not expose port 8000 to the
public internet. After testing, remove the override and recreate the API:

```powershell
Remove-Item Env:PULSEHUNTER_API_BIND
docker compose up --detach --wait
```

## Laptop setup

Once this milestone is approved and pushed, clone it on the laptop (or copy
the current uncommitted checkout there for a pre-commit manual test). The
laptop has Python 3.14.7; run these commands in PowerShell:

```powershell
git clone https://github.com/MdFahimBashar/PulseHunter.git
Set-Location PulseHunter
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install ".[host-agent]"
```

If you copied the uncommitted checkout, skip `git clone` and `Set-Location`.

Check that the active network profile is `Private`:

```powershell
Get-NetConnectionProfile
```

In an **elevated PowerShell window**, add one inbound rule for the desktop's
address only. Creating a firewall rule needs elevation; running the agent does
not. Replace the example desktop IP if it changes:

```powershell
New-NetFirewallRule -DisplayName 'PulseHunter host agent' -Direction Inbound `
  -Action Allow -Protocol TCP -LocalPort 9000 -Profile Private `
  -RemoteAddress '192.168.30.198'
```

Then use a **normal, non-elevated PowerShell window** in the repository root
to start the agent:

```powershell
.\.venv\Scripts\pulsehunter-host-agent.exe `
  --server http://192.168.30.198:8000 `
  --public-url http://192.168.30.83:9000 `
  --name fahim-laptop
```

The process listens on `0.0.0.0:9000` but advertises the configured LAN URL.
Leave this terminal running. The laptop registers as `windows-host` with
`simulated=false` and sends a heartbeat every two seconds. When it stops, the
control plane marks it offline after the heartbeat timeout.

## Verify and run

On the desktop, confirm that the worker can reach the agent through the LAN:

```powershell
docker compose exec -T worker python -c "import urllib.request; print(urllib.request.urlopen('http://192.168.30.83:9000/health', timeout=5).status)"
```

Then select **only the laptop** for the dedicated `host-health` suite:

```powershell
$device = Invoke-RestMethod http://127.0.0.1:8000/devices |
  Where-Object name -eq 'fahim-laptop' | Select-Object -First 1
if (-not $device -or $device.status -ne 'online') { throw 'Laptop agent is not online' }
docker compose exec -T api pulsehunter-ci run --server http://127.0.0.1:8000 `
  --suite host-health --device-id $($device.id) --wait --timeout 60
```

The command prints the run ID and exits `0` only if the host checks pass. Open
`http://127.0.0.1:8000/` and select that run to inspect the persisted result.
The agent reports OS/host/architecture, CPU counts, RAM, disk, uptime, IP
addresses, optional battery information, and bounded memory and temporary-file
integrity results. Hostname and IP information are persisted in PostgreSQL;
use this only on a trusted network.

Always select the laptop explicitly. PulseHunter does not yet match suite
capabilities to devices: an all-device `host-health` run would also assign the
simulators, whose results are not physical-host evidence. The host agent
rejects other suite definitions rather than running arbitrary instructions.
The existing simulator `smoke` suite and three agents remain unchanged.

The worker gives `windows-host` jobs a 10-second HTTP deadline and a longer
lease; simulator jobs keep their 3-second deadline. This is a bounded timeout,
not a long-running stress test. A direct agent request or restart can still
lose its in-memory idempotency cache. Restrict both API and agent ports to the
trusted LAN until authentication and TLS are implemented.
