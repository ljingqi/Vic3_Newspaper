# -*- coding: utf-8 -*-
"""P5b: full snapshot pipeline — extract_full_snapshot -> build_journal_data,
verify snap['map'] is present and survives into the data dict."""
import json
import os
import sys

sys.path.insert(0, r"D:/Journal")
import journal_save as js

with open(r"D:/Journal/tools/melt.json", "rb") as f:
    data = f.read()

ctx = js.SaveContext(data)
snap = js.extract_full_snapshot(data, ctx=ctx)
print("snap keys with map:", "map" in snap)
m = snap.get("map")
if m:
    print("map.main:", len(m["main"]), "overseas:", len(m["overseas"]))
    print("map.states:", len(m.get("states") or {}),
          "sample:", list((m.get("states") or {}).items())[:1])
else:
    print("map is None!")

jdata = js.build_journal_data(snap)
print("\njournal data has map:", "map" in jdata)
if jdata.get("map"):
    print("journal map.states:", len(jdata["map"].get("states") or {}))
print("journal data player:", jdata.get("player"), "year:", jdata.get("year"))
