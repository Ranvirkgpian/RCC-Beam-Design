import ezdxf

def export_to_dxf(filepath, s):
    """Generates a 1:1 scale CAD DXF drawing of the beam cross-section."""
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    
    # 1. Draw Concrete Beam Outline (Color: White/Black)
    msp.add_lwpolyline([(0, 0), (s.b, 0), (s.b, s.D), (0, s.D), (0, 0)])
    
    # 2. Draw Stirrup (Color: Red)
    cc = s.effective_cover - 8  # Clear cover
    sx1, sy1 = cc, cc
    sx2, sy2 = s.b - cc, s.D - cc
    msp.add_lwpolyline(
        [(sx1, sy1), (sx2, sy1), (sx2, sy2), (sx1, sy2), (sx1, sy1)], 
        dxfattribs={'color': 1} # 1 = Red in AutoCAD
    )
    
    stirrup_dia = s.shear.stirrup_dia if s.shear else 8

    # 3. Draw Bottom Tension Bars (Color: Cyan)
    if s.bar_selection:
        num_bars = s.bar_selection.num_bars
        dia = s.bar_selection.bar_dia
        y_cen = cc + stirrup_dia + (dia / 2)
        start_x = cc + stirrup_dia + (dia / 2)
        end_x = s.b - cc - stirrup_dia - (dia / 2)
        
        for i in range(num_bars):
            x_cen = start_x + i * ((end_x - start_x) / (num_bars - 1)) if num_bars > 1 else s.b / 2
            msp.add_circle((x_cen, y_cen), dia / 2, dxfattribs={'color': 4}) # 4 = Cyan

    # 4. Draw Top Compression/Anchor Bars (Color: Yellow)
    if getattr(s, 'comp_bar_selection', None):
        c_num_bars = s.comp_bar_selection.num_bars
        c_dia = s.comp_bar_selection.bar_dia
        cy_cen = s.D - cc - stirrup_dia - (c_dia / 2)
        c_start_x = cc + stirrup_dia + (c_dia / 2)
        c_end_x = s.b - cc - stirrup_dia - (c_dia / 2)
        
        for i in range(c_num_bars):
            cx_cen = c_start_x + i * ((c_end_x - c_start_x) / (c_num_bars - 1)) if c_num_bars > 1 else s.b / 2
            msp.add_circle((cx_cen, cy_cen), c_dia / 2, dxfattribs={'color': 2}) # 2 = Yellow

    doc.saveas(filepath)