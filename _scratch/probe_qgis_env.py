# -*- coding: utf-8 -*-
"""Test QGIS Python env: shapely availability + polygonize provinces."""
import sys
print("python:", sys.version)
for m in ["shapely", "geopandas", "fiona", "rasterio", "numpy", "PIL", "matplotlib", "osgeo"]:
    try:
        mod = __import__(m)
        print(m, "OK", getattr(mod, "__version__", "?"))
    except Exception as e:
        print(m, "MISSING", str(e)[:80])
