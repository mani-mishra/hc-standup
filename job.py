import asyncio
from datetime import datetime
from aiohttp_ac_hipchat.util import http_request
from pytz import timezone, utc
import sys

import app


force = sys.argv and len(sys.argv) == 2 and sys.argv[1] == "--force"


@asyncio.coroutine
def execute():
    webapp = app.app
    yield from webapp.trigger_hook('before_first_request')
    addon = webapp.addon

    clients = yield from addon.load_all_clients()

    reports = []
    for client in clients:
        report = asyncio.Task(try_client(addon, client))
        reports.append(report)

    print("Waiting on %s reports" % len(reports))
    yield from asyncio.wait(reports)

    print("Job complete")


@asyncio.coroutine
def try_client(addon, client):
    token = yield from client.get_token(addon.redis, scopes=["view_group"])
    headers = {"Authorization": "Bearer %s" % token}
    with (yield from http_request('GET', client.room_base_url + "?expand=participants",
                                  headers=headers, timeout=10)) as resp:
        if resp.status == 200:
            body = yield from resp.read(decode=True)
            standup_user_mentions = []
            for user in body['participants']:
                is_available = not 'show' in user['presence']
                if 'timezone' in user and is_available:
                    tz = timezone(user['timezone'])
                    u_ts = datetime.utcnow()
                    u_utc = u_ts.replace(tzinfo=utc)
                    now = tz.normalize(u_utc.astimezone(tz))
                    print("User %s hour: %s tz: %s actual_tx: %s" %
                          (user['name'], now.strftime("%H"), now, user['timezone']))
                    if int(now.strftime("%H")) == 9 or force:
                        standup_user_mentions.append(user['mention_name'])

            if standup_user_mentions:
                _, statuses = yield from app.find_statuses(addon, client)
                if statuses:
                    status_mentions = [status['user']['mention_name'] for status in statuses.values()]
                    standup_user_mentions = [mention for mention in standup_user_mentions
                                             if mention in status_mentions]
                    if standup_user_mentions:
                        mentions_with_at = ["@" + mention for mention in standup_user_mentions]
                        yield from client.send_notification(addon,
                                                            text="10 AM standup for %s" % " "
                                                            .join(mentions_with_at))
                        yield from app.display_all_statuses(addon, client)

        elif resp.status == 404:
            print("weird...")
        else:
            raise Exception("Invalid response: %s" % (yield from resp.read()))


loop = asyncio.get_event_loop()
loop.run_until_complete(asyncio.Task(execute()))
