# -*- coding: utf-8 -*-

'''
Object representing rectangles and lines, which is parsed from both raw streams and annotations of pdf.

@created: 2020-07-22
@author: train8808@gmail.com
---

Rectangle data structure:
    {
        'type': int,
        'bbox': (x0, y0, x1, y1),
        'color': sRGB_value
    }
'''

import copy
from .base import RectType
from pdf2docx import utils


class Rectangles:
    ''' A group of rectangle objects.'''
    def __init__(self):
        ''' Construct Text blocks (image blocks included) from a list of raw block dict.'''
        self._rects = []

    def __getitem__(self, idx):
        try:
            rects = self._rects[idx]
        except IndexError:
            msg = f'Rectangle shape index {idx} out of range'
            raise IndexError(msg)
        else:
            return rects

    def __iter__(self):
        return (rect for rect in self._rects)

    def __len__(self):
        return len(self._rects)

    def from_annotations(self, annotations: list):
        ''' Get rect from annotations(comment shapes) in PDF page
            Note: consider highlight, underline, strike-through-line only. 
            ---
            Args:
                - annotations: a list of PyMuPDF Annot objects        
        '''
        # map rect type from PyMuPDF
        # Annotation types:
        # https://pymupdf.readthedocs.io/en/latest/vars.html#annotation-types   
        # PDF_ANNOT_HIGHLIGHT 8
        # PDF_ANNOT_UNDERLINE 9
        # PDF_ANNOT_SQUIGGLY 10
        # PDF_ANNOT_STRIKEOUT 11
        type_map = { 
            8 : RectType.HIGHLIGHT, 
            9 : RectType.UNDERLINE, 
            11: RectType.STRIKE
        }

        for annot in annotations:

            # consider highlight, underline, strike-through-line only.
            # e.g. annot.type = (8, 'Highlight')
            key = annot.type[0]
            if not key in (8,9,11): 
                continue
            
            # color, e.g. {'stroke': [1.0, 1.0, 0.0], 'fill': []}
            c = annot.colors.get('stroke', (0,0,0)) # black by default

            # convert rect coordinates
            rect = annot.rect

            raw = {
                'bbox': (rect.x0, rect.y0, rect.x1, rect.y1),
                'color': utils.RGB_value(c)
            }
            rect = Rectangle(raw)
            rect.type = type_map[key]

            self._rects.append(rect)

    def from_stream(self, xref_stream: str, height: float):
        ''' Get rectangle shape by parsing page cross reference stream.

            Note: these shapes are generally converted from pdf source, e.g. highlight, underline, 
            which are different from PDF comments shape.

            ---
            Args:
                - xref_streams: doc._getXrefStream(xref).decode()        
                - height: page height for coordinate system conversion from pdf CS to fitz CS 

            --------            
            References:
                - https://www.adobe.com/content/dam/acom/en/devnet/pdf/pdf_reference_archive/pdf_reference_1-7.pdf
                    - Appendix A for associated operators
                    - Section 8.5 Path Construction and Painting
                - https://github.com/pymupdf/PyMuPDF/issues/263

            typical mark of rectangle in xref stream:
                /P<</MCID 0>> BDC
                ...
                1 0 0 1 90.0240021 590.380005 cm
                ...
                1 1 0 rg # or 0 g
                ...
                285.17 500.11 193.97 13.44 re f*
                ...
                214 320 m
                249 322 l
                ...
                EMC

            where,
                - `MCID` indicates a Marked content, where rectangles exist
                - `cm` specify a coordinate system transformation, 
                here (0,0) translates to (90.0240021 590.380005)
                - `q`/`Q` save/restores graphic status
                - `rg` / `g` specify color mode: rgb / grey
                - `re`, `f` or `f*`: fill rectangle path with pre-defined color. If no `f`/`f*` coming after
                `re`, it's a rectangle with borders only (no filling).
                in this case,
                    - fill color is yellow (1,1,0)
                    - lower left corner: (285.17 500.11)
                    - width: 193.97
                    - height: 13.44
                - `m`, `l`: draw line from `m` (move to) to `l` (line to)

            Note: coordinates system transformation should be considered if text format
                is set from PDF file with edit mode. 
        '''
        # Graphic States:
        # - working CS is coincident with the absolute origin (0, 0)
        # consider scale and translation only
        ACS = [1.0, 1.0, 0.0, 0.0] # scale_x, scale_y, translate_x, tranlate_y
        WCS = [1.0, 1.0, 0.0, 0.0]

        # - graphics color: 
        #   - stroking color
        Acs = utils.RGB_value((0.0, 0.0, 0.0)) # stored value
        Wcs = Acs                              # working value
        #   - filling color
        Acf = utils.RGB_value((0.0, 0.0, 0.0))
        Wcf = Acf

        # - stroke width
        Ad = 0.0
        Wd = 0.0

        # In addition to lines, rectangles are also processed with border path
        paths = [] # a list of path, each path is a list of points

        # check xref stream word by word (line always changes)    
        begin_text_setting = False    
        lines = xref_stream.split()

        for (i, line) in enumerate(lines):

            # skip any lines between `BT` and `ET`, 
            # since text setting has no effects on shape        
            if line=='BT':  # begin text
                begin_text_setting = True
        
            elif line=='ET': # end text
                begin_text_setting = False

            if begin_text_setting:
                continue        

            # CS transformation: a b c d e f cm, e.g.
            # 0.05 0 0 -0.05 0 792 cm
            # refer to PDF Reference 4.2.2 Common Transformations for detail
            if line=='cm':
                # update working CS
                sx = float(lines[i-6])
                sy = float(lines[i-3])
                tx = float(lines[i-2])
                ty = float(lines[i-1])
                WCS = [WCS[0]*sx, WCS[1]*sy, WCS[2]+tx, WCS[3]+ty]

            # painting color
            # - reset color space
            elif line.upper()=='CS':
                Wcs = utils.RGB_value((0.0, 0.0, 0.0))
                Wcf = utils.RGB_value((0.0, 0.0, 0.0))

            # - gray mode
            elif line.upper()=='G':  # 0 g
                g = float(lines[i-1])
                # nonstroking color, i.e. filling color here
                if line=='g':
                    Wcf = utils.RGB_value((g, g, g))
                # stroking color
                else:
                    Wcs = utils.RGB_value((g, g, g))

            # - RGB mode
            elif line.upper()=='RG': # 1 1 0 rg
                r, g, b = map(float, lines[i-3:i])

                #  nonstroking color
                if line=='rg':
                    Wcf = utils.RGB_value((r, g, b))
                # stroking color
                else:
                    Wcs = utils.RGB_value((r, g, b))

            # - CMYK mode
            elif line.upper()=='K': # c m y k K
                c, m, y, k = map(float, lines[i-4:i])
                #  nonstroking color
                if line=='k':
                    Wcf = utils.CMYK_to_RGB(c, m, y, k, cmyk_scale=1.0)
                # stroking color
                else:
                    Wcs = utils.CMYK_to_RGB(c, m, y, k, cmyk_scale=1.0)

            # - set color: either gray, or RGB or CMYK mode
            elif line.upper()=='SC': # c1 c2 ... cn SC
                c = _RGB_from_color_components(lines[i-4:i])
                #  nonstroking color
                if line=='sc':
                    Wcf = c
                # stroking color
                else:
                    Wcs = c

            # - set color: either gray, or RGB or CMYK mode
            elif line.upper()=='SCN': # c1 c2 ... cn [name] SC
                if utils.is_number(lines[i-1]):
                    c = _RGB_from_color_components(lines[i-4:i])
                else:
                    c = _RGB_from_color_components(lines[i-5:i-1])

                #  nonstroking color
                if line=='scn':
                    Wcf = c
                # stroking color
                else:
                    Wcs = c

            # stroke width
            elif line=='w':
                Wd = float(lines[i-1])

            # save or restore graphics state:
            # only consider transformation and color here
            elif line=='q': # save
                ACS = copy.copy(WCS)
                Acf = Wcf
                Acs = Wcs
                Ad = Wd
                
            elif line=='Q': # restore
                WCS = copy.copy(ACS)
                Wcf = Acf
                Wcs = Acs
                Wd = Ad

            # rectangle block:
            # x y w h re is equivalent to
            # x   y   m
            # x+w y   l
            # x+w y+h l
            # x   y+h l
            # h          # close the path
            elif line=='re': 
                # ATTENTION: 
                # top/bottom, left/right is relative to the positive direction of CS, 
                # while a reverse direction may be performed, so be careful when calculating
                # the corner points. 
                # Coordinates in the transformed PDF CS:
                #   y1 +----------+
                #      |          | h
                #   y0 +----w-----+
                #      x0        x1
                # 

                # (x, y, w, h) before this line            
                x0, y0, w, h = map(float, lines[i-4:i])
                path = []
                path.append((x0, y0))
                path.append((x0+w, y0))
                path.append((x0+w, y0+h))
                path.append((x0, y0+h))
                path.append((x0, y0))

                paths.append(path)

            # lines: m -> move to point to start a path
            elif line=='m':
                x0, y0 = map(float, lines[i-2:i])
                paths.append([(x0, y0)])
            
            # lines: l -> straight line to point
            elif line=='l':
                x0, y0 = map(float, lines[i-2:i])
                paths[-1].append((x0, y0))

            # close the path
            elif line=='h': 
                for path in paths:
                    _close_path(path)

            # close and stroke the path
            elif line.upper()=='S':
                # close
                if line=='s':
                    for path in paths:
                        _close_path(path)

                # stroke path
                for path in paths:
                    rects = _stroke_path(path, WCS, Wcs, Wd, height)
                    res.extend(rects)

                # reset path
                paths = []

            # fill the path
            elif line in ('f', 'F', 'f*'):            
                for path in paths: 
                    # close the path implicitly
                    _close_path(path)
                
                    # fill path
                    rect = _fill_rect_path(path, WCS, Wcf, height)
                    if rect: res.append(rect)

                # reset path
                paths = []

            # close, fill and stroke the path
            elif line.upper() in ('B', 'B*'): 
                for path in paths: 
                    # close path
                    _close_path(path)
                    
                    # fill path
                    rect = _fill_rect_path(path, WCS, Wcf, height)
                    if rect: res.append(rect)

                    # stroke path
                    rects = _stroke_path(path, WCS, Wcs, Wd, height)
                    res.extend(rects)

                # reset path
                paths = []

            # TODO: clip the path
            elif line in ('W', 'W*'):
                pass

            # end the path without stroking or filling
            elif line=='n':
                paths = []
        
        return res

    @staticmethod
    def _transform_path(path: list, WCS: list, height: float) -> list:
        ''' Transform path to page coordinate system. 
            ---
            Args:
                - path: a list of (x,y) point
                - WCS: transformation matrix
                - height: page height for converting CS from pdf to fitz
        '''
        res = []
        sx, sy, tx, ty = WCS
        for (x0, y0) in path:
            # transformate to original PDF CS                    
            x = sx*x0 + tx
            y = sy*y0 + ty

            # pdf to PyMuPDF CS
            y = height-y
            
            res.append((x, y))

        return res


    def _stroke_path(self, path: list, WCS: list, color: int, width: float, page_height: float):
        ''' Stroke path with a given width. Only horizontal/vertical paths are considered.
        '''
        # CS transformation
        t_path = self._transform_path(path, WCS, page_height)

        rects = []
        for i in range(len(t_path)-1):
            # start point
            x0, y0 = t_path[i]
            # end point
            x1, y1 = t_path[i+1]

            # ensure from top-left to bottom-right
            if x0>x1 or y0>y1:
                x0, y0, x1, y1 = x1, y1, x0, y0

            # convert line to rectangle with a default height 0.5pt
            centerline = (x0, y0, x1, y1)
            rect = centerline_to_rect(centerline, color, width)
            if rect:
                rects.append(rect)
        return rects


    def _fill_rect_path(path, WCS, color, page_height):
        ''' Fill bbox of path with a given color. Only horizontal/vertical paths are considered.
        '''
        # CS transformation
        t_path = _transform_path(path, WCS, page_height)

        # find bbox of path region
        X = [p[0] for p in t_path]
        Y = [p[1] for p in t_path]
        x0, x1 = min(X), max(X)
        y0, y1 = min(Y), max(Y)

        # filled rectangle
        rect = {
            'type': -1,
            'bbox': (x0, y0, x1, y1), 
            'color': color
        }
            
        return rect


    def _RGB_from_color_components(components):
        ''' Detect color mode from given components and calculate the RGB value.
            ---
            Args:
                - components: a list with 4 elements
        '''
        color = utils.RGB_value((0.0,0.0,0.0))

        # CMYK mode
        if all(map(utils.is_number, components)):
            c, m, y, k = map(float, components)
            color = utils.CMYK_to_RGB(c, m, y, k, cmyk_scale=1.0)

        # RGB mode
        elif all(map(utils.is_number, components[1:])):
            r, g, b = map(float, components[1:])
            color = utils.RGB_value((r, g, b))

        # gray mode
        elif utils.is_number(components[-1]):
            g = float(components[-1])
            color = utils.RGB_value((g,g,g))

        return color

