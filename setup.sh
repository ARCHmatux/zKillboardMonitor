#!/bin/bash
# This script performs inital setup for zKillMon.
# At present it is assumed that zKillMon will live in /opt/zKillMon
# ToDo: Validate paths

sudo adduser --system --group zkillmon --home /opt/zKillMon
sudo chown --recursive zkillmon /opt/zKillMon
sudo cp -v /opt/zKillMon/zkillmon.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable zkillmon
sudo systemctl start zkillmon
sudo systemctl status zkillmon