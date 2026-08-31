# -*- coding: utf-8 -*-
from PIL import Image
import numpy as np
im = np.array(Image.open(r"D:/Journal/_scratch/map_v4_fullres.png").convert("RGB"))
flat = im.reshape(-1, 3)
cols, counts = np.unique(flat, axis=0, return_counts=True)
order = np.argsort(-counts)[:8]
for i in order:
    print("#%02X%02X%02X" % tuple(cols[i]), int(counts[i]))
# fraction of beige vs sea
beige = np.all(flat == [239, 230, 207], axis=1).mean()
sea = np.all(flat == [220, 234, 242], axis=1).mean()
print("beige land fraction: %.3f | sea fraction: %.3f" % (beige, sea))
