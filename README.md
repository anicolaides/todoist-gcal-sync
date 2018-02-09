# todoist_gcal_sync
Bi-directional syncing between Todoist and Google Calendar


## Getting Started
First and foremost, why ... use Google Calendar with Todoist?
> The norm for a To-do app is to display tasks in a *linear fashion*; yet, one can't help but realize how overwhelming this approach may turn out to be.
> Nonetheless, **Visualization** is a plausible solution to this challenge; through this integration, one can visualize and plan ahead by looking at a bird's eye view of the whole landscape available for work.

The instructions below will help you get the tool up and running.


------
*Note*: The daemon has only been tested with unix-based systems and python 3.x.

### Prerequisites
For an always up-to-date list of dependencies - see [dependencies.txt](/misc/dependencies.txt)

Install dependencies using:
```
pip3 install -r /misc/dependencies.txt
```

### Installing
1. Clone the repo and change dir.
```bash
git clone https://github.com/alexandrosio/todoist_gcal_sync.git
cd ./todoist_gcal_sync
```

2. Create the credentials folder.
```shell
mkdir credentials
```

3. Create the `todoist_token` file.
```shell
touch credentials/todoist_token
cd credentials/
vi todoist_token
```
and paste your Todoist API token into _`todoist_token`_.

4. Sign in to your Google account and visit [Google Cloud](https://console.cloud.google.com/cloud-resource-manager) to create a project.
    1. Click on `CREATE PROJECT`.
    2. Type "todoist-gcal-sync" as Project name and click the `Create` button.
    
    _Note: a project todoist-gcal-sync-XXXXX will be created._
    
    3. Select project todoist-gcal-sync-XXXXX from the drop-down.

    4. While looking at the project's dashboard, click on the the `Products & services` located at the top left-hand corner of the screen and select `APIs and Services`.

    5. Then, click on `ENABLE APIS AND SERVICES` and select `Google Calendar API`.

    6. Then, click on the `ENABLE` button.

    7. Then, click on `Credentials` followed by the `OAuth consent screen` tab.

    8. Now, type "todoist-gcal-sync" under "Product name shown to users" and click `Save`.

    9. Click on the `Credentials` tab, followed by the `Create credentials` button and select the `OAuth client ID` option.

    10. Then, select the `Other` option, and type "python" as Application type followed by the `Create` button.

    11. Then, download the client secret file in JSON format using the download button.

    12. Rename the client secret file to `client_secret.json` and place it under the "/credentials" folder.

5. Configure the SMTP logging handlder of the [log_cfg.json](/config/log_cfg.json) file by replacing `YOUR_GMAIL_USERNAME` and `ONE_TIME_APP_PASSWORD` with the appropriate information; if you are using Two-Factor Authentication with Gmail, simply create a one-time app password; otherwise, use your existing Gmail password.

6. Now edit [settings.json](/config/settings.json) according to your needs; if you'd like to exclude some projects or mark others as standalone, then this is the time to make those changes.

Please find attached a sample of my excluded/standalone projects' config.
```json
  ...
 // User Preferences
 "projects.excluded": ["Someday | Maybe"],
 "projects.standalone": ["Side projects", "todoist_gcal_sync"],
  ...
```

7. Run the app for the first time.
```shell
cd ..
python3 daemon.py --noauth_local_webserver
```

8. Copy the link provided to your browser and paste the `verification code` generated to the machine that's running the daemon.

### How to run the daemon
```shell
python3 daemon.py
```

### How to run the daemon in the background (for testing purposes)
```shell
nohup python3 -u ./daemon.py > /dev/null 2>&1&
```

## How to run the daemon as a service (using systemd)
1. Move and rename the systemd service file.
   ```shell
   sudo mv /misc/systemd_service_file /lib/systemd/system/todoist-gcal-sync.service
   ```
2. Edit the service file,
   ```shell
   sudo vi /lib/systemd/system/todoist-gcal-sync.service
   ```
   and change `PATH_TO_CLONED_REPO` to the path of the local copy of this repository on your server.

3. Refresh systemd.
   ```shell
   systemctl daemon-reload
   ```

4. Enable the service, so it persists on reboot.
   ```shell
   sudo systemctl enable todoist-gcal-sync.service
   ```

5. Run the service.
   ```shell
   sudo systemctl start todoist-gcal-sync.service
   ```
Finally, run the following to confirm the service is up and running:
   ```shell
   sudo service todoist-gcal-sync status
   ```
_Note: If you had initialized todoist-gcal-sync with a non-root user, you may have to re-initialize the daemon using `python3 daemon.py --noauth_local_webserver` as google creates a credentials folder per user._
## How to reset the daemon

```shell
touch reset_daemon
python3 daemon.py
```
_Note: This will erase all calendars and the app's database, then re-initialize the app._

## How to migrate the app to a new system

1. Copy contents of .todoist_sync to the destination system.
2. Copy the database to the destination system.
3. Run daemon.py.

## Contributing
Please feel free to contribute as the project is still at its infancy. Any help is greatly appreciated.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details