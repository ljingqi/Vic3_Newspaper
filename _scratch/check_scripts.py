# -*- coding: utf-8 -*-
idx = open(r"D:/Journal/_scratch/sess_map_test/index.html", encoding="utf-8").read()
print("open <script count:", idx.count("<script"))
print("close </script count:", idx.count("</script>"))
# find all script blocks' positions
import re
for m in re.finditer(r"<script[^>]*>", idx):
    print("script at", m.start(), ":", m.group(0)[:60])
# check the tail: is 'bindMapTips' inside a script block?
i = idx.find("function bindMapTips")
print("bindMapTips at", i)
# check what precedes the ARTICLES const — ensure no leaked '</script>'
j = idx.find("const ARTICLES")
print("const ARTICLES at", j)
print("context before:", repr(idx[j-60:j]))
