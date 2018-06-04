__all__ = ['tileServer','fileTile','arrayTile']
import os
import re
#import tornado.ioloop
import tornado.web

from io import BytesIO
from PIL import Image, ImageDraw
import mercantile
from affine import Affine
import rasterio
import numpy as np
import pyproj

from matplotlib import cm

class tinyTile_Server(object):
    '''creates a very minimal slippy map tile server
    
    uses the jupyter notebook tornado.ioloop'''
    #TODO: make option to standalone outside of jupyter
    def __init__(self):
        self.layers = {}
        application = tornado.web.Application([
            (r"^/livemaptiles/(\w+)(?:/cache(\d+))?(?:/compress(\d))?/(\d+)/(\d+)/(\d+)\.(bmp|png)$", MainHandler,{"layers" : self.layers}),
            (r"/.*", ErrorHandler)])
        self._server = tornado.httpserver.HTTPServer(application)
        self.port = 8080
    
    def start(self):
        self._server.listen(self.port)#,address='127.0.0.1')
    def stop(self):
        self._server.stop()

class ErrorHandler(tornado.web.RequestHandler):
    def get(self):
        raise tornado.web.HTTPError(404)
        
class MainHandler(tornado.web.RequestHandler):
    def initialize(self, layers):
        self.layers = layers
    def compute_etag(self):
        '''Im not using etags so save on the computation of a hash
        
        could be changed so that the user can increment a flag in layers when the layer changes 
        this could force invalidation of any cached tiles
        '''
        #http://www.tornadoweb.org/en/stable/web.html#tornado.web.RequestHandler.compute_etag
        return None

    def get(self,layer,cache,compress,z,x,y,file_ext):
        if compress is None:
            compress = 0
        self.set_header("Content-type",  "image/{}".format(file_ext))
        if cache is None:
            self.set_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        else:
            #This is a little blunt. But without a lot of cross browser testing lets keep it simple.
            self.set_header('Cache-Control', 'max-age={}'.format(cache))
        if layer not in self.layers:
            im = textTile('layer does not exist')
        else:
            im = self.layers[layer](layer,int(z),int(x),int(y))
        self.write(PIL_image_in_bytes(im,file_ext,int(compress)))

def PIL_image_in_bytes(image,file_ext ='png',compress=0):
    '''Takes a PIL image and returns bytes representing a file
    
    file_ext is expected to be either png or bmp.
    compress only works for png and is in the range 0 - 9
    if compress = 9 the the pil png writer optimize command is used.
    '''
    byte_io = BytesIO()
    image.save(byte_io, file_ext, compress_level=compress,optimize=compress==9)
    byte_io.seek(0)
    return byte_io.getvalue()
          
def debugTileMaker(layer,z,x,y):
    '''writes useful information on a tile'''
    return textTile(str((layer,z,x,y)))
    
def textTile(text='Error'):
    '''writes text on a tile'''
    image = Image.new("RGB", (256, 256))
    draw = ImageDraw.Draw(image)
    draw.text((50, 120), text)
    return image


tileServer = tinyTile_Server()
tileServer.layers['debug'] = debugTileMaker
tileServer.start()

class fileTile(object):
    '''simple example tile maker for any 3 band file that rasterio can read
     
    Optionally set resampling method to one of
    rasterio.enums.Resampling default is nearest
    The filename and resampling can be changed at any time and 
    tileMaker will start producing tiles with the new settings'''    
    def __init__(self,fileName):
        self.fileName = fileName
        self.resampling = rasterio.enums.Resampling.nearest
    
    def tileMaker(self,layer,z,x,y):
        '''
        NOTE: seems to get stuck if you zoom way way out.
        '''
        with rasterio.open(self.fileName) as src:
            with rasterio.vrt.WarpedVRT(src, dst_crs='EPSG:3857',
                           resampling=self.resampling) as vrt:
                # Determine the window to use in reading from the dataset.
                #go from x,y,z tile coordinates to spherical mercator coordinates to raster pixel coordinates
                dst_window = vrt.window(*mercantile.xy_bounds(x,y,z))
                data = vrt.read(window=dst_window, out_shape=(3, 256, 256),boundless=True,fill_value=0)
                im = Image.fromarray(np.transpose(data, [1,2,0]))
                return im

class memfileTile(object):
    '''simple example tile maker for any 3 band array that rasterio can read
     
    Optionally set resampling method to one of
    rasterio.enums.Resampling default is nearest
    The in_array or other settings can be changed at any time and 
    tileMaker will start producing tiles with the new settings'''    
    def __init__(self,in_array,in_affine,in_crs):
        self.in_array = in_array
        self.in_affine = in_affine
        self.in_crs = in_crs
        self.resampling = rasterio.enums.Resampling.nearest
    
    def tileMaker(self,layer,z,x,y):
        '''
        NOTE: seems to get stuck if you zoom way way out.
        NOTE: creating the memfile each time is slow and chews up ram as it copies in_array
        It does give flexibility to modify the in_array.
        '''
        
        specs = dict(driver='GTiff',width=self.in_array.shape[1],height=self.in_array.shape[2],count=3,dtype=self.in_array.dtype,crs=self.in_crs,transform=self.in_affine)
        memfile = rasterio.io.MemoryFile()
        with memfile.open(**specs) as src:
            src.write(self.in_array)
            with rasterio.vrt.WarpedVRT(src, dst_crs='EPSG:3857',
                           resampling=self.resampling) as vrt:
                # Determine the window to use in reading from the dataset.
                #go from x,y,z tile coordinates to spherical mercator coordinates to raster pixel coordinates
                dst_window = vrt.window(*mercantile.xy_bounds(x,y,z))
                data = vrt.read(window=dst_window, out_shape=(3, 256, 256),boundless=True,fill_value=0)
                im = Image.fromarray(np.transpose(data, [1,2,0]))
                return im


def _datum_check():
    textfile = open(os.path.join(pyproj.pyproj_datadir,'epsg'), 'r')
    filetext = textfile.read()
    textfile.close()
    return re.findall(r"\n<(\d{4})>.*datum=WGS84", filetext)
            
class arrayTile(object):
    '''tile maker for a 2d numpy array
    
    This quite fast and as almost no extra memory overhead even when working with large arrays
    This is strictly only using nearest neighbour resampling
    
    The in_array or other settings can be changed at any time and 
    tileMaker will start producing tiles with the new settings'''    
    def __init__(self,in_array,in_affine,in_crs):
        self.in_array = in_array
        self.in_affine = in_affine
        self.in_crs = in_crs
        self.colourMap = cm.binary
        self.scale_min = 0
        self.scale_max = 1
        self.alpha = None
        self._epsg_with_wgs84_datum = _datum_check()


    def array_resampler(self,z,x,y):
        '''
        uses a somewhat unusual approach to  reprojecting an array.
        instead of reprojecting the array it projects points that represent the cell centres in the desired output array
        These points are then used to select the cells in the input array
        '''
        #interesting background info on plate carree projection ie geographic projection
        #https://idvux.wordpress.com/2007/06/06/mercator-vs-well-not-mercator-platte-carre/
        numPixels = 256
        #EPSG:4326 wgs84
        #3857 is spherical mercator
        p1 = pyproj.Proj(init='epsg:3857')
        p2 = pyproj.Proj(self.in_crs)
        inverse_src_affine = ~self.in_affine

        #make_transform
        dst_affine =rasterio.transform.from_bounds(*mercantile.xy_bounds(x,y,z), width=numPixels,height=numPixels)

        xarr = np.arange(0,numPixels)
        coords = np.meshgrid(xarr,xarr)
        
        #speed things up if a full projection is not required
        #pyproj transform takes a while even if p1 and p2 are the same. Also if p1 and p2 share a datum less work is required
        #datum check isnt exhustive but if the projection is defined with an epsg code then it will catch it.
        same_projection = 'epsg:3857' in p2.srs
        epsg_srs = re.search(r'epsg:(\d{4})',p2.srs)
        same_datum = epsg_srs and epsg_srs.group(1) in self._epsg_with_wgs84_datum
        if same_projection:
            float_indexes = inverse_src_affine * (dst_affine * coords)
        elif 'epsg:4326' in p2.srs:
            #wgs84 plate carree projection ie geographic projection with same datum as epsg:3857
            float_indexes = inverse_src_affine * p1(*(dst_affine * coords),inverse=True)
        elif same_datum:
            float_indexes = inverse_src_affine * p2(*p1(*(dst_affine * coords),inverse=True))
        else:
            float_indexes = inverse_src_affine * pyproj.transform(p1, p2, *(dst_affine * coords))

        indexes =(np.floor(float_indexes[1]).astype(int),np.floor(float_indexes[0]).astype(int))

        #simpler fancy indexing but doesnt do any bounds checking
        #outData = self.in_array[indexes]

        #bounds checking
        valid_indexes = (indexes[0]>=0) & (indexes[0]<=self.in_array.shape[0]-1) & (indexes[1]>=0) & (indexes[1]<=self.in_array.shape[1]-1)
        if hasattr(self.in_array,'vindex'):
            #oooh we might have something like a zarr array
            valid_values = self.in_array.vindex[indexes[0][valid_indexes],indexes[1][valid_indexes]]
        else:
            #just an ndarray
            valid_values = self.in_array[indexes[0][valid_indexes],indexes[1][valid_indexes]]
        outData = np.zeros((numPixels,numPixels),dtype=np.float)
        outData[valid_indexes] = valid_values
        return outData
    

        
    def tileMaker(self,layer,z,x,y):
        tile_array = self.array_resampler(z,x,y)
        #scale sectionof interest 0 - 1 so that the colour map can be applied.
        tile_array -= self.scale_min
        tile_array /= self.scale_max - self.scale_min
        im = Image.fromarray(self.colourMap(tile_array, alpha=self.alpha, bytes=True))
        return im
