import json
import csv
import re
import os
from dotenv import load_dotenv

load_dotenv()
EMU_TENANT = os.getenv("EMU_TENANT")

INPUT_FILE = "ecatalogue_schema.json"
OUTPUT_FILE = "ecatalogue_fields.csv"

with open(INPUT_FILE, "r") as f:
    schema = json.load(f)

properties = schema["data"]["properties"]

with open(OUTPUT_FILE, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["field_name", "type", "format", "repeatable", "ref_target"])

    for field_name, field_def in properties.items():
        field_type = field_def.get("type")
        field_format = field_def.get("format", "")

        if field_name.endswith("_tab") or field_name.endswith("_nesttab") or field_name.endswith("_grp"):
            repeatable = "yes"
        elif field_type == "array":
            repeatable = "yes"
        else:
            repeatable = ""

        ref_target = ""
        pattern = field_def.get("pattern", "")
        if pattern:
            match = re.search(rf"emu:/{EMU_TENANT}/([^/]+)/", pattern)
            if match:
                ref_target = match.group(1)

        writer.writerow([field_name, field_type, field_format, repeatable, ref_target])

print(f"Field list saved to {OUTPUT_FILE}")