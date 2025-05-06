sudo cp install/projects_flight_calendar_updater.service /lib/systemd/system/projects_flight_calendar_updater.service

sudo chmod 644 /lib/systemd/system/projects_flight_calendar_updater.service

sudo systemctl daemon-reload
sudo systemctl daemon-reexec

sudo systemctl enable projects_flight_calendar_updater.service
