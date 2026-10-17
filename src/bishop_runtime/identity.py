"""Bishop's original engraved-metal mark, sampled into terminal braille.

Geometry is shared conceptually with assets/bishop-kedolabs-agent-runtime-logo.svg.
No font, image decoder or terminal graphics extension is required.
"""
import math

# Cross-section of the mitre, collar, waist and stepped architectural foot.
_PROFILE = ((11,0),(15,7),(21,13),(28,17),(34,17.5),(39,14),
            (43,7),(45,7),(46,21),(49,21),(50,13),(53,11),
            (57,8),(63,7),(69,9),(73,13),(75,19),(78,22),
            (80,22),(81,18),(84,18),(85,28),(88,28),(89,32),(93,32))
_BAYER = ((0,8,2,10),(12,4,14,6),(3,11,1,9),(15,7,13,5))
_BITS = ((0,3),(1,4),(2,5),(6,7))
_PALETTE = ((118,81,46),(182,138,77),(218,184,121),(244,220,166))


def _radius(y):
    for (a,ra),(b,rb) in zip(_PROFILE,_PROFILE[1:]):
        if a <= y <= b:
            t=(y-a)/(b-a)
            # The head is smoothly turned; the lower geometry is crisp.
            if b <= 43: t=t*t*(3-2*t)
            return ra+(rb-ra)*t
    return -1


def _sample(x,y):
    r=_radius(y)
    if r <= 0 or abs(x)>r: return None
    # Finial, physically separate from the mitre.
    # Mitre incision enters from the upper right and terminates at centre.
    if 17 <= y <= 34 and abs(x-(32-y)*.72)<1.65: return None
    u=x/max(r,1)
    light=.42 + .42*max(0,1-abs(u+.34)*1.15)
    # Facet edges and thin lathed engraving in the metal.
    if -.57 < u < -.43: light+=.18
    if .23 < u < .34: light-=.17
    if any(abs(y-v)<.45 for v in (47.5,50.5,76.5,79.5,86.5,90.5)): light*=.48
    if abs(x)>r-1: light=max(light,.68 if x<0 else .4)
    return max(.16,min(1,light))


def emblem(width=24,height=23,color=False):
    """Return exactly ``height`` rows of ``width`` display cells.

    ANSI truecolour is optional; removing it yields the identical plain mark.
    Bounds prevent accidental unbounded rendering from configuration values.
    """
    if type(width) is not int or type(height) is not int or not 1<=width<=200 or not 1<=height<=200:
        raise ValueError('emblem dimensions must be integers from 1 to 200')
    rows=[]
    for cy in range(height):
        row=[]
        for cx in range(width):
            bits=0; values=[]
            for dy in range(4):
                for dx in range(2):
                    sx=cx*2+dx; sy=cy*4+dy
                    x=((sx+.5)/(width*2)-.5)*82
                    y=(sy+.5)/(height*4)*100
                    value=_sample(x,y)
                    # A small turned finial is separated by negative space.
                    if (x/2.5)**2+((y-6)/2.5)**2<=1: value=.93
                    if value is not None:
                        values.append(value)
                        threshold=(_BAYER[sy%4][sx%4]+.5)/16
                        if value*.76+.18>threshold: bits|=1<<_BITS[dy][dx]
            char=chr(0x2800+bits) if bits else ' '
            if color and bits:
                level=min(3,int(sum(values)/len(values)*4))
                r,g,b=_PALETTE[level]
                char=f'\x1b[38;2;{r};{g};{b}m{char}\x1b[0m'
            row.append(char)
        rows.append(''.join(row))
    return rows
