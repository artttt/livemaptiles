# livemaptiles
a minimal slippy map tile server that functions in a jupyter notebook session. The idea is that you use it for making a quick tile server for exploring data on the fly.

If you use it feedback is appreciated.

To help you get started it is recommended that you look at livemaptiles_demo.ipynb

a couple of things that might trip you up early on.
 - Wont work outside of a Jupyter notbook.
 - it uses port 8080 by default on import. If that is in use you will get some errors. However you can change the port and then start the server 

you can install it directly from github like this
```
pip install https://github.com/artttt/livemaptiles/archive/master.zip
```

I havnt documented the dependancies as yet but here is the list of imports needed
```
import re
import tornado.web
from io import BytesIO
from PIL import Image, ImageDraw
import mercantile
from affine import Affine
import rasterio
import numpy as np
from pyproj import Transformer,CRS
from matplotlib import cm
```
