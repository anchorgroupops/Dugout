# Dugout Autopull — systemd units

Install on the Pi:

```bash
cd ~/dugout
sudo cp deploy/systemd/gc-autopull.service /etc/systemd/system/
sudo cp deploy/systemd/gc-autopull.timer /etc/systemd/system/
sudo cp deploy/systemd/gc-autopull-weekly.service /etc/systemd/system/
sudo cp deploy/systemd/gc-autopull-weekly.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gc-autopull.timer
sudo systemctl enable --now gc-autopull-weekly.timer
```

Verify:

```bash
systemctl list-timers | grep autopull
journalctl -u gc-autopull.service --since today
```

Pause the daily run without removing the units: set `GC_AUTOPULL_ENABLED=false`
in `.env`. The timer still fires but the CLI exits early with
`outcome=skipped`.
