# Ported to Python 3 from MGLTools Vision/PILNodes.py
# Original: Michel Sanner, Daniel Stoffler (TSRI). Port: Michel Sanner, PhD. Copyright (c) 2026.
"""Imaging: read, filter, combine, measure and save images (PIL / Pillow).

Converted mechanically (wewos.legacy.py2to3), then: the old PIL module names
and calls are updated (Image.fromstring -> frombytes, import Image -> from
PIL import Image...); Show Image shows the image in a panel of the page
instead of a Tk window; Grab Image takes a snapshot of a 3D viewer from the
page instead of reading the OpenGL front buffer; the MPEG nodes (pymedia)
are not ported.
"""
import numpy
from PIL import Image
import types
import math

from wewos.engine import NetworkNode, NodeLibrary
from wewos.engine.datatypes import AnyArrayType


class ImageFromArray(NetworkNode):
    """based on the Image.open function. Reads an image file
Input:  filename (string)
Output: Image"""
    
    def __init__(self, name='Image from array', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        code = """def doit(self, array, width, height, normalize, linkRGB): 
    lennar = len(array)
    if lennar != width * height:
        import warnings
        print ("Image from array: width * height must be equal to len(array)")
        return
    if hasattr(array[0], '__len__') is False or len(array[0]) == 1:
        lenarray = 1
    elif len(array[0]) == 3:
        lenarray = 3
    elif len(array[0]) == 4:
        lenarray = 4
        
    nar = numpy.array(array)
    narOriginalShape = nar.shape
    nar.shape = (width*height*lenarray,)

    if isinstance(nar[0], float):

        if normalize == 1:
            nar.shape = narOriginalShape
            if lenarray == 1:
                mininar = min(nar)
                maxinar = max(nar)
                ecartnar = maxinar - mininar
                if ecartnar > 0:
                    for i in range(lennar):
                        nar[i] = (nar[i] - mininar) / ecartnar
            else:
                narChannel = list(range(lennar))
                mininar = [0,0,0,0]
                maxinar = [0,0,0,0]
                for j in range(lenarray):
                    for i in range(lennar):
                        narChannel[i] = nar[i][j]
                    mininar[j] = min(narChannel)
                    maxinar[j] = max(narChannel)

                if linkRGB == 1:
                    mininarGlobal = min(mininar[0], mininar[1], mininar[2])
                    mininar[0] = mininarGlobal
                    mininar[1] = mininarGlobal
                    mininar[2] = mininarGlobal
                    maxinarGlobal = max(maxinar[0], maxinar[1], maxinar[2])
                    maxinar[0] = maxinarGlobal
                    maxinar[1] = maxinarGlobal
                    maxinar[2] = maxinarGlobal

                for j in range(lenarray):
                    ecartnar = maxinar[j] - mininar[j]
                    if ecartnar > 0:
                        for i in range(lennar):
                            nar[i][j] = (nar[i][j] - mininar[j]) / ecartnar

        nar.shape = (width*height*lenarray,)
        for i in range(len(nar)):
            nar[i] = int(math.floor( 255.999 * nar[i] ))
    nar = nar.astype(numpy.uint8)
    
    from PIL import Image
    if lenarray == 1:
        im = Image.frombytes('L', (width, height), nar.tobytes()) 
    elif lenarray == 3:
        im = Image.frombytes('RGB', (width, height), nar.tobytes()) 
    elif lenarray == 4:
        im = Image.frombytes('RGBA', (width, height), nar.tobytes()) 
    if im:
        self.outputData(image=im)
"""

        self.setFunction(code)

        self.inputPortsDescr.append(datatype='list', name='array')
        self.inputPortsDescr.append(datatype='int', name='width')
        self.inputPortsDescr.append(datatype='int', name='height')
        self.inputPortsDescr.append(datatype='boolean', name='normalize')
        self.inputPortsDescr.append(datatype='boolean', name='linkRGB')
        self.outputPortsDescr.append(datatype='image', name='image')

        self.widgetDescr['normalize'] = {
            'class':'NECheckButton',
            'master':'node',
            'initialValue':False,
            'labelGridCfg':{'sticky':'we'},
            'labelCfg':{'text':'normalize floats'},
            }

        self.widgetDescr['linkRGB'] = {
            'class':'NECheckButton',
            'master':'node',
            'initialValue':True,
            'labelGridCfg':{'sticky':'we'},
            'labelCfg':{'text':'link RGB normalization'},
            }



class ReadImage(NetworkNode):
    """based on the Image.open function. Reads an image file
Input:  filename (string)
Output: Image"""
    
    def __init__(self, name='Read Image', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)
        self.inNodeWidgetsVisibleByDefault = True

        #self.readOnly = 1
        code = """def doit(self, filename):
    if filename:
        from PIL import Image
        im = Image.open(filename)
        if im:
            self.outputData(image=im)\n"""

        self.setFunction(code)

        fileTypes = [('all', '*'), ('jpeg', '*.jpg'), ('tiff', '*.tif'),
                     ('png', '*.png'), ('bmp', '*.bmp')]

        self.widgetDescr['filename'] = {
            'class':'NEEntryWithFileBrowser', 'master':'node',
            'filetypes':fileTypes, 'title':'read image', 'width':10,
                    'labelCfg':{'text':'image file:'} }

        self.inputPortsDescr.append(datatype='str', name='filename')
        self.outputPortsDescr.append(datatype='image', name='image')


class SaveImage(NetworkNode):
    """saves an image."""
    
    def __init__(self, name='Save Image', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)
        #self.readOnly = 1
        code = """def doit(self, image, filename):
    if filename:
        image.save(filename)\n"""

        self.setFunction(code)

        fileTypes = [('all', '*')]

        self.widgetDescr['filename'] = {
            'class':'NEEntryWithFileSaver', 'master':'node',
            'filetypes':fileTypes, 'title':'save image', 'width':10,
            'labelCfg':{'text':'image file:'} }

        self.inputPortsDescr.append(datatype='image', name='image')
        self.inputPortsDescr.append(datatype='str', name='filename')






class ToRGB(NetworkNode):
    """converts an Image to RGB"""

    def __init__(self, name='To RGB', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        self.inputPortsDescr.append(datatype='image', name='image')

        self.outputPortsDescr.append(datatype='image', name='RGBimage')
        
        code = """def doit(self, image):
    if image.mode!='RGB':
        image.draft('RGB', image.size)
        image = image.convert('RGB')
    self.outputData(RGBimage=image)\n"""

        self.setFunction(code)


class ResizeImage(NetworkNode):
    """Resize image using scaling factor supplied by dial. The filter argument
    can be NEAREST, BILINEAR, or BICUBIC. If omitted, it defaults to NEAREST.
    """
    
    def __init__(self, name='Resize', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)
        self.inNodeWidgetsVisibleByDefault = True

        code = """def doit(self, image, scale, filter):
    from PIL import Image
    w,h = image.size
    if filter is not None and filter != '':
        op = eval('Image.'+filter)
        result = image.resize( (int(round(w*scale)), int(round(h*scale))), op )
    else:
        result = image.resize( (int(round(w*scale)), int(round(h*scale))) )
    
    self.outputData( scaledImage=result )\n"""

        if code: self.setFunction(code)

        self.widgetDescr['scale'] = {
            'class': 'NEThumbWheel', 'master':'node', 'width':75, 'height':28,
            'type': 'float', 'oneTurn': 1.0, 'min':0.01,
            'initialValue':1.0, 
            'labelCfg':{'text':'Scale'},
            }

        filters = ['NEAREST','BILINEAR','BICUBIC' ]
        self.widgetDescr['filter'] = {
            'class':'NEComboBox', 
            'choices':filters,
            'fixedChoices':True,
            'initialValue':'NEAREST',
            'entryfield_entry_width':12,
            'labelCfg':{'text':'filter'},
            'widgetGridCfg':{'labelSide':'top'},
            }
        
        ip = self.inputPortsDescr
        ip.append(datatype='image', name='image')
        ip.append(datatype='float', name='scale')
        ip.append(datatype='string', name='filter')

        op = self.outputPortsDescr
        op.append(datatype='image', name='scaledImage')


class ImageFilter(NetworkNode):
    """Apply different filters to an image"""

    def __init__(self, name='Filter Image', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        filters = ['BLUR', 'CONTOUR', 'DETAIL', 'EDGE_ENHANCE',
                   'EDGE_ENHANCE_MORE', 'EMBOSS', 'FIND_EDGES',
                   'SMOOTH', 'SMOOTH_MORE', 'SHARPEN' ]

        self.widgetDescr['filter'] = {
            'class':'NEComboBox', 'master':'node',
            'choices':filters,
            'fixedChoices':True,
            'entryfield_entry_width':14,
            'labelCfg':{'text':'filter:'},
            }

        ip = self.inputPortsDescr
        ip.append(datatype='image', name='image')
        ip.append(datatype='None', name='filter')

        self.outputPortsDescr.append(datatype='image', name='image')
        
        code = """def doit(self, image, filter):
    from PIL import ImageFilter
    if filter and image:
        op = getattr(ImageFilter, filter)
        self.outputData(image= image.filter(op))\n"""

        self.setFunction(code)


class ImageInvert(NetworkNode):
    """Inverts an image."""

    def __init__(self, name='Invert Image', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        self.inputPortsDescr.append(datatype='image', name='image')

        self.outputPortsDescr.append(datatype='image', name='image')
        
        code = """def doit(self, image):
    from PIL import ImageChops
    self.outputData(image = ImageChops.invert(image))\n"""

        self.setFunction(code)


class ImageMultiply(NetworkNode):
    """Superimposes two images on top of each other. If you multiply an
image with a solid black image, the result is black. If you multiply with
a solid white image, the image is unaffected."""
    
    def __init__(self, name='Multiply Image', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        ip = self.inputPortsDescr
        ip.append(datatype='image', name='image1')
        ip.append(datatype='image', name='image2')

        self.outputPortsDescr.append(datatype='image', name='image')
        
        code = """def doit(self, image1, image2):
    from PIL import ImageChops
    self.outputData(image = ImageChops.multiply(image1, image2))\n"""

        self.setFunction(code)


class ImageSplit(NetworkNode):
    """Apply different filters to an image"""

    def __init__(self, name='Split Image', **kw):
        NetworkNode.__init__(*(self,), **kw)

        self.inputPortsDescr.append(datatype='image', name='image')

        op = self.outputPortsDescr
        op.append(datatype='None', name='r')
        op.append(datatype='None', name='g')
        op.append(datatype='None', name='b')
        
        code = """def doit(self, image):
    r,g,b = image.split()
    self.outputData(r=r, g=g, b=b)\n"""

        self.setFunction(code)


class AlphaMask(NetworkNode):
    """
    Build a mask for an image based ona  threshold value.
    The mask will have 0 values for evry pixel with intensity below the
    threshold value. THis mask can be used as the third input of a composite
    node for instance to blend 2 images only where the mask is not 0.
    """

    def __init__(self, name='Alpha Mask', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        self.widgetDescr['threshold'] = {
            'class':'NEDial', 'master':'node', 'size':50,
            'labelCfg':{'text':'threshold'},
            'widgetGridCfg':{'labelSide':'top'},
            }

        ip = self.inputPortsDescr
        ip.append(datatype='image', name='image')
        ip.append(datatype='image', name='threshold')

        self.outputPortsDescr.append(datatype='None', name='mask')

        code = """def doit(self, image, threshold):
    l = lambda x,cutOff=threshold: (x > cutOff)*255
    mask = image.point( l )
    self.outputData(mask=mask)\n"""

        self.setFunction(code)


class ImagePaste(NetworkNode):
    """Apply different filters to an image"""

    def __init__(self, name='Invert Image', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        ip = self.inputPortsDescr
        ip.append(datatype='image', name='image1')
        ip.append(datatype='image', name='image2')
        ip.append(datatype='None', name='mask')

        self.outputPortsDescr.append(datatype='image', name='image')
        
        code = """def doit(self, image1, image2, mask):
    image1.paste(image2, None, mask)
    self.outputData(image=image1)\n"""

        self.setFunction(code)
        



class ImageBlend(NetworkNode):
    """Creates a new image by interpolating between the given images,
using a constant alpha. Both images must have the same size and mode.
If alpha is 0.0, a copy of the first image is returned. If alpha is 1.0,
a copy of the second image is returned. There are no restrictions on the
alpha value. If necessary, the result is clipped to fit into the allowed
output range."""

    def __init__(self, name='Invert Image', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        self.widgetDescr['alpha'] = {
            'class': 'NEDial', 'master':'node', 'size':50,
            'type':'float', 'min':0,
            'lockMin':1, 'lockBMin':1, 'lockType':1, 'max':1.0,
            'lockMax':1, 'lockBMax':1, 'oneTurn':0.1,
            'initialValue':0.5,
            'labelCfg':{'text':'alpha'},
            'widgetGridCfg':{'labelSide':'top'},
            }
        
        ip = self.inputPortsDescr
        ip.append(datatype='image', name='image1')
        ip.append(datatype='image', name='image2')
        ip.append(datatype='float', name='alpha')

        self.outputPortsDescr.append(datatype='image', name='image')
        
        code = """def doit(self, image1, image2, alpha):
    from PIL import Image
    result = Image.blend(image1, image2, alpha)
    self.outputData(image=result)\n"""

        self.setFunction(code)
    
 
class ImageRotate(NetworkNode):
    """Returns a copy of an image rotated the given number of degrees counter
clockwise around its centre. The filter argument can be NEAREST, BILINEAR,
or BICUBIC. If omitted, it defaults to NEAREST. """

    def __init__(self, name='Rotate', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        self.widgetDescr['angle'] = {
            'class': 'NEThumbWheel', 'master':'node', 'width':75, 'height':28,
            'type':'float','initialValue':0.0,
            'labelCfg':{'text':'angle'},
            }

        filters = ['NEAREST','BILINEAR','BICUBIC' ]
        self.widgetDescr['filter'] = {
            'class':'NEComboBox', 
            'choices':filters,
            'fixedChoices':True,
            'initialValue':'NEAREST',
            'entryfield_entry_width':12,
            'labelCfg':{'text':'filter'},
            'widgetGridCfg':{'labelSide':'top'},
            }
        
        ip = self.inputPortsDescr
        ip.append(datatype='image', name='image')
        ip.append(datatype='float', name='angle')
        ip.append(datatype='string', name='filter')

        self.outputPortsDescr.append(datatype='image', name='image')
        
        code = """def doit(self, image, angle, filter):
    if filter is not None and filter != '':
        from PIL import Image
        op = eval('Image.'+filter)
        result = image.rotate(angle, op)
    else:
        result = image.rotate(angle)
    self.outputData(image=result)\n"""

        self.setFunction(code)
        

class ImageTranspose(NetworkNode):
    """Returns a flipped or rotated copy of an image.  Method can be one of
    the following: FLIP_LEFT_RIGHT, FLIP_TOP_BOTTOM, ROTATE_90, ROTATE_180,
    or ROTATE_270."""

    def __init__(self, name='Transpose', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        methods = ['FLIP_LEFT_RIGHT','FLIP_TOP_BOTTOM','ROTATE_90',
                   'ROTATE_180', 'ROTATE_270']
        self.widgetDescr['method'] = {
            'class':'NEComboBox', 'master':'node',
            'choices':methods,
            'fixedChoices':True,
            'entryfield_entry_width':14,
            'labelCfg':{'text':'methods:'},
            }

        ip = self.inputPortsDescr
        ip.append(datatype='image', name='image')
        ip.append(datatype='string', name='method')

        self.outputPortsDescr.append(datatype='image', name='image')
        
        code = """def doit(self, image, method):
    if method is not None and method != '':
        from PIL import Image
        op = eval('Image.'+method)
        result = image.transpose(op)
    else:
        result = image
    self.outputData(image=result)\n"""

        self.setFunction(code)


class ImageComposite(NetworkNode):
    """Creates a new image by interpolating between the given images, using
the mask as alpha. The mask can be either 1, L, or RGBA. All images must have
the same size."""

    def __init__(self, name='Composite', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        ip = self.inputPortsDescr
        ip.append(datatype='image', name='image1')
        ip.append(datatype='image', name='image2')
        ip.append(datatype='image', name='mask')

        self.outputPortsDescr.append(datatype='image', name='image')
        
        code = """def doit(self, image1, image2, mask):
    from PIL import Image
    result = Image.composite(image1, image2, mask)
    self.outputData(image=result)\n"""

        self.setFunction(code)


class ImageStat(NetworkNode):
    """This node calculates global statistics for an image, or a region of an
image. If a mask is included, only the  regions covered by that mask are
included in the statistics."""

    def __init__(self, name='Image Stat', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        stats = ['extrema','count','sum','sum2','mean','median','rms','var',
                 'stddev']

        self.widgetDescr['stat'] = {
            'class':'NEComboBox', 'master':'node',
            'choices':stats,
            'fixedChoices':True,
            'entryfield_entry_width':7,
            'labelCfg':{'text':'methods:'},
            }

        ip = self.inputPortsDescr
        ip.append(datatype='image', name='image')
        #ip.append(datatype='image', required=False, name='mask')
        ip.append(datatype='string', required=False, name='stat')

        self.outputPortsDescr.append(datatype='None', name='stats')
        
        code = """def doit(self, image, stat):
    if stat is not None and stat != '':
        from PIL import ImageStat
        data = ImageStat.Stat(image)
        result = eval('data.'+stat)
        self.outputData(stats=result)\n"""

        self.setFunction(code)

 

    


# ---------------------------------------------------------------------------------------
# WEWoS: the image type, and the nodes that used Tk or OpenGL
# ---------------------------------------------------------------------------------------

class ImageType(AnyArrayType):
    """'image': a PIL image."""

    def __init__(self, name='image', datashape=None, color='#995699', shape='rect',
                 width=None, height=None):
        AnyArrayType.__init__(self, name=name, color=color, shape=shape, klass=Image.Image)


def image_png(image, maxsize=1600):
    """A PNG data URL of image (scaled down to maxsize pixels at most)."""
    import base64
    import io
    im = image
    if max(im.size) > maxsize:
        im = im.copy()
        im.thumbnail((maxsize, maxsize))
    if im.mode not in ('RGB', 'RGBA', 'L', 'LA', 'P'):
        im = im.convert('RGBA')
    buf = io.BytesIO()
    im.save(buf, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')


class ShowImage(NetworkNode):
    """Show an image in a panel of the page (in the row of panels under the
network, beside the 3D viewers).

Input Ports
    image: the image to show
"""

    def __init__(self, name='Show Image', **kw):
        kw['name'] = name
        NetworkNode.__init__(self, **kw)
        self.image = None
        self.imageVersion = 0
        self.inputPortsDescr.append(datatype='image', name='image')
        self.setFunction("""def doit(self, image):
    self.showImage(image)
""")

    def showImage(self, image):
        self.image = image
        self.imageVersion += 1
        if self.network is not None:
            self.network.emit('image', node=self.id, name=self.name,
                              version=self.imageVersion, size=list(image.size))

    def imageData(self):
        if self.image is None:
            return {'png': None}
        return {'png': image_png(self.image), 'size': list(self.image.size),
                'mode': self.image.mode, 'version': self.imageVersion}

    def describe(self):
        d = NetworkNode.describe(self)
        d['imageViewer'] = True
        return d


class GetFrontBuffer(NetworkNode):
    """Take a snapshot of a 3D viewer as an image (Vision read the OpenGL
front buffer; here the page sends the picture the viewer shows).
The page must be open, with the viewer visible.

Input Ports
    viewer: the 'viewer' output of a Viewer node
    cameraNum: not used (kept for networks made with Vision)
Output Ports
    image: an RGBA image
"""

    def __init__(self, name='Grab Image', **kw):
        kw['name'] = name
        NetworkNode.__init__(self, **kw)
        self.inputPortsDescr.append(datatype='viewer', name='viewer')
        self.inputPortsDescr.append(datatype='int', required=False, name='cameraNum')
        self.outputPortsDescr.append(datatype='image', name='image')
        self.setFunction("""def doit(self, viewer, cameraNum):
    self.outputData(image=viewer.snapshot())
""")


imagelib = NodeLibrary('Imaging', '#C38DB5',
                       doc='images with PIL: read, filter, combine, show, save')
imagelib.addType(ImageType())

imagelib.addNode(ImageFromArray, 'Image from array', 'Input')
imagelib.addNode(ReadImage, 'Read Image', 'Input')
imagelib.addNode(GetFrontBuffer, 'Grab Image', 'Input')
#imagelib.addNode(GetZBuffer, 'RecordMPEGmovie', 'Input')

imagelib.addNode(ShowImage, 'Show Image', 'Output')
imagelib.addNode(ImageStat, 'Image Stat', 'Output')
imagelib.addNode(SaveImage, 'Save Image', 'Output')


imagelib.addNode(ToRGB, 'ToRGB', 'Filter')
imagelib.addNode(ImageFilter, 'Filter Image', 'Filter')
imagelib.addNode(ImageInvert, 'Invert Image', 'Filter')
imagelib.addNode(ImageSplit, 'Split Image', 'Filter')
imagelib.addNode(AlphaMask, 'Build Mask', 'Filter')
imagelib.addNode(ImagePaste, 'Paste Images', 'Filter')

imagelib.addNode(ResizeImage, 'Scale', 'Mapper')
imagelib.addNode(ImageBlend, 'Blend', 'Mapper')
imagelib.addNode(ImageMultiply, 'Multiply', 'Mapper')
imagelib.addNode(ImageComposite, 'Composite', 'Mapper')
imagelib.addNode(ImageRotate, 'Rotate', 'Mapper')
imagelib.addNode(ImageTranspose, 'Transpose', 'Mapper')




