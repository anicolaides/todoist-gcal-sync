from todoist_gcal_sync.utils.auth.gcal_OAuth import get_credentials
from todoist_gcal_sync.utils import sql_ops
import httplib2
from apiclient import discovery

gcal_creds = get_credentials()
http = gcal_creds.authorize(httplib2.Http())

# 'cache_discovery=False' is used to circumvent the file_cache issue for oauth2client >= 4.0.0
# More info on the issue here: https://github.com/google/google-api-python-client/issues/299
service = discovery.build('calendar', 'v3', http=http, cache_discovery=False)

cal_ids = sql_ops.select_from_where(
    "calendar_id, calendar_sync_token", "gcal_ids", None, None, fetch_all=True)


def google_code(cal_id, sync_token):
    next_sync_token = None
    page_token = None
    while True:
        events = service.events().list(calendarId=cal_id, pageToken=page_token,
                                       syncToken=sync_token).execute()
        for event in events['items']:
            print(event['summary'])

        if 'nextSyncToken' in events:
            next_sync_token = events['nextSyncToken']

        page_token = events.get('nextPageToken')
        if not page_token:
            break
    return next_sync_token


for i in range(0, len(cal_ids)):
    sync_token = google_code(cal_ids[i][0], cal_ids[i][1])
    if sql_ops.update_set_where(
            "gcal_ids", "calendar_sync_token = ?", "calendar_id = ?", sync_token, cal_ids[i][0]):
        print("Calendar sync token updated.")
