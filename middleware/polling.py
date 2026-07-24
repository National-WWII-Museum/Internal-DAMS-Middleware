"""
polling.py
Scheduled entry point - checks EMu for records modified since the last
successful run, processes them, and updates the sync state.
Intended to be run once a day via Windows Task Scheduler.
"""

from . import state
from . import emu_client

MODULE = "ecatalogue"  # starting with just Catalogue for now


def run():
    # Step 1: make sure the database and tables exist
    state.init_db()

    # Step 2: find out where we left off last time
    last_sync_date = state.get_last_sync_date(MODULE)
    # print(f"Last sync date for {MODULE}: {last_sync_date}")

    # Step 3: ask EMu for everything modified since that date
    records = emu_client.search_modified_since(MODULE, last_sync_date)
    # print(f"Found {len(records)} record(s) modified since {last_sync_date}")

    if records:
        sample = records[0]
        # print("Sample irn value:", repr(sample.get("irn")))
        # print("Sample irn type:", type(sample.get("irn")))

    # Step 4: filter out anything already synced for its exact modified date.
    # Fetch already-synced IRNs once per distinct date, not once per record.
    distinct_dates = {record.get("AdmDateModified") for record in records}
    synced_by_date = {
        date: state.get_synced_irns_for_date(MODULE, date)
        for date in distinct_dates
    }

    new_records = []
    for record in records:
        irn = record.get("irn")
        date_modified = record.get("AdmDateModified")
        if irn not in synced_by_date[date_modified]:
            new_records.append(record)

    print(f"{len(new_records)} record(s) remain after filtering already-synced")


if __name__ == "__main__":
    run()