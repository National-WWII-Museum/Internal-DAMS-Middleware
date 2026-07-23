"""
polling.py
Scheduled entry point - checks EMu for records modified since the last
successful run, processes them, and updates the sync state.
Intended to be run once a day via Windows Task Scheduler.
"""
from datetime import datetime

from . import state
from . import emu_client

MODULE = "ecatalogue"  # just Catalogue for now


def run():
    state.init_db()

    #find out where we left off last time
    last_sync_date = state.get_last_sync_date(MODULE)
    print(f"Last sync date for {MODULE}: {last_sync_date}")

    #ask EMu for everything modified since that date
    records = emu_client.search_modified_since(MODULE, last_sync_date)
    print(f"Found {len(records)} record(s) modified since {last_sync_date}")


if __name__ == "__main__":
    run()