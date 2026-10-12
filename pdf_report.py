"""
pdf_report.py - Professional PDF Report Generator for RCC Beam Designer
Supports partial report generation based on the active step and imports IS 456 charts.
Includes high-fidelity detailing drawings using ReportLab graphics.
"""

import os
import math
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
from reportlab.platypus import Image as RLImage
from reportlab.graphics.shapes import Drawing, Rect, Circle, String, Group, PolyLine, Line

def add_reference_image(filepath, target_width, is_dark):
    """Helper to embed an image cleanly if it exists in the assets folder."""
    if os.path.exists(filepath):
        img = ImageReader(filepath)
        iw, ih = img.getSize()
        aspect = ih / float(iw)
        return RLImage(filepath, width=target_width, height=(target_width * aspect))
    else:
        color = "#F8FAFC" if is_dark else "#000000"
        return Paragraph(f"<i><font color='{color}'>[Note: Reference image '{filepath}' not found.]</font></i>", getSampleStyleSheet()['Normal'])

def generate_pdf_report(filepath, session, max_step=6, is_dark=False):
    if is_dark:
        COLOR_BG = colors.HexColor("#0F172A")
        COLOR_CARD = colors.HexColor("#1E293B")
        COLOR_PRIMARY = colors.HexColor("#93C5FD")
        COLOR_TEXT = colors.HexColor("#F8FAFC")
        COLOR_LINE = colors.HexColor("#334155")
        COLOR_SAFE = colors.HexColor("#34D399")
        COLOR_FAIL = colors.HexColor("#FCA5A5")
        COLOR_SUBTEXT = colors.HexColor("#94A3B8")
    else:
        COLOR_BG = colors.HexColor("#F8FAFC")
        COLOR_CARD = colors.white
        COLOR_PRIMARY = colors.HexColor("#1A3052")
        COLOR_TEXT = colors.black
        COLOR_LINE = colors.HexColor("#CBD5E1")
        COLOR_SAFE = colors.HexColor("#16A34A")
        COLOR_FAIL = colors.HexColor("#DC2626")
        COLOR_SUBTEXT = colors.HexColor("#64748B")

    c_concrete = colors.HexColor("#1E293B") if is_dark else colors.HexColor("#F1F5F9")
    c_stirrup = colors.HexColor("#EF4444") if is_dark else colors.HexColor("#DC2626")
    c_tens = colors.HexColor("#EF4444") if is_dark else colors.HexColor("#DC2626")
    c_comp = colors.HexColor("#F8FAFC") if is_dark else colors.black
    c_dim = colors.HexColor("#94A3B8") if is_dark else colors.HexColor("#64748B")

    styles = getSampleStyleSheet()
    style_title = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=18, textColor=COLOR_PRIMARY, alignment=1, spaceAfter=8)
    style_h1 = ParagraphStyle('H1Style', parent=styles['Heading2'], fontName='Helvetica-Bold', fontSize=14, textColor=COLOR_PRIMARY, spaceBefore=12, spaceAfter=6)
    style_h2 = ParagraphStyle('H2Style', parent=styles['Heading3'], fontName='Helvetica-Bold', fontSize=10, textColor=COLOR_PRIMARY, spaceBefore=10, spaceAfter=4)
    style_normal = ParagraphStyle('NormalStyle', parent=styles['Normal'], fontName='Helvetica', fontSize=10, textColor=COLOR_TEXT, spaceAfter=4, leading=14)
    style_math = ParagraphStyle('MathStyle', parent=styles['Normal'], fontName='Helvetica', fontSize=10, textColor=COLOR_TEXT, leftIndent=20, spaceBefore=3, spaceAfter=6, leading=16)

    doc = SimpleDocTemplate(filepath, pagesize=A4, rightMargin=15*mm, leftMargin=15*mm, topMargin=15*mm, bottomMargin=15*mm)
    story = []
    s = session

    # 1. COVER
    story.append(Paragraph("RCC BEAM DESIGNER", style_title))
    story.append(Paragraph("IS 456:2000 — LIMIT STATE DESIGN", ParagraphStyle('Sub', parent=style_title, fontSize=12, spaceAfter=15)))

    proj_data = [
        ["Project Name:", "RCC Beam Design Calculation", "Date:", "Auto-generated"],
        ["Design Code:", "IS 456:2000", "Units:", "mm, kN, N/mm²"],
        ["Report Type:", "Complete Report" if max_step == 6 else "Partial Report", "Revision:", "0"]
    ]
    t_proj = Table(proj_data, colWidths=[35*mm, 60*mm, 25*mm, 45*mm])
    t_proj.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
        ('FONTWEIGHT', (0,0), (0,-1), 'bold'),
        ('FONTWEIGHT', (2,0), (2,-1), 'bold'),
        ('TEXTCOLOR', (0,0), (-1,-1), COLOR_PRIMARY),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(t_proj)
    story.append(Spacer(1, 8*mm))

    # 2. DESIGN INPUT SUMMARY
    story.append(Paragraph("1. DESIGN INPUT SUMMARY", style_h1))
    input_data = [
        ["GEOMETRY", "", "MATERIAL", ""],
        ["Beam Width (b)", f"{s.b:.0f} mm", "Concrete Grade", f"{s.concrete_grade}"],
        ["Overall Depth (D)", f"{s.D:.0f} mm", "fck", f"{int(s.concrete_grade.replace('M',''))} N/mm²"],
        ["Effective Cover", f"{s.effective_cover:.0f} mm", "Steel Grade", f"{s.steel_grade}"],
        ["Span (L)", f"{s.span:.2f} m", "fy", f"{int(s.steel_grade.replace('Fe',''))} N/mm²"],
        ["Support Condition", f"{s.beam_type}", "", ""],
        ["DESIGN LOADS", "", "", ""],
        ["Factored Moment (Mu)", f"{s.mu:.2f} kN·m", "Factored Shear (Vu)", f"{s.vu:.2f} kN"]
    ]
    t_input = Table(input_data, colWidths=[40*mm, 40*mm, 40*mm, 40*mm])
    t_input.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), COLOR_CARD),
        ('BACKGROUND', (0,6), (-1,6), COLOR_CARD),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTNAME', (0,6), (-1,6), 'Helvetica-Bold'),
        ('TEXTCOLOR', (0,0), (-1,0), COLOR_PRIMARY),
        ('TEXTCOLOR', (0,6), (-1,6), COLOR_PRIMARY),
        ('TEXTCOLOR', (0,1), (-1,5), COLOR_TEXT),
        ('TEXTCOLOR', (0,7), (-1,7), COLOR_TEXT),
        ('LINEBELOW', (0,0), (-1,0), 1, COLOR_LINE),
        ('LINEBELOW', (0,6), (-1,6), 1, COLOR_LINE),
        ('FONTNAME', (0,1), (0,5), 'Helvetica-Bold'),
        ('FONTNAME', (2,1), (2,5), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(t_input)
    story.append(Spacer(1, 6*mm))

    # 3. FLEXURAL DESIGN
    if max_step >= 2 and s.flexural:
        f = s.flexural
        story.append(Paragraph("2. FLEXURAL DESIGN", style_h1))
        story.append(Paragraph("2.1 Effective Depth", style_h2))
        story.append(Paragraph(f"d = D - effective cover = {s.D} - {s.effective_cover} = <b>{f.d:.1f} mm</b>", style_math))
        story.append(Paragraph("2.2 Limiting Neutral Axis & Moment", style_h2))
        story.append(Paragraph(f"x<sub>u,max</sub> = <b>{f.xu_max:.2f} mm</b><br/>M<sub>lim</sub> = <b>{f.m_lim:.2f} kN·m</b>", style_math))
        story.append(Paragraph("2.3 Section Classification", style_h2))
        if f.is_singly:
            story.append(Paragraph(f"M<sub>u</sub> ({s.mu:.2f}) &le; M<sub>lim</sub> ({f.m_lim:.2f}) &rarr; <b>SINGLY REINFORCED</b>", style_math))
        else:
            story.append(Paragraph(f"M<sub>u</sub> ({s.mu:.2f}) &gt; M<sub>lim</sub> ({f.m_lim:.2f}) &rarr; <b>DOUBLY REINFORCED</b><br/>A<sub>sc</sub> required = {s.doubly.asc:.1f} mm²", style_math))
        story.append(Spacer(1, 6*mm))

    # 4. SHEAR DESIGN
    if max_step >= 3 and s.shear:
        sh = s.shear
        story.append(Paragraph("3. SHEAR DESIGN", style_h1))
        story.append(Paragraph("3.1 Shear Stress Checks", style_h2))
        story.append(Paragraph(f"&tau;<sub>v</sub> = <b>{sh.tau_v:.3f} N/mm²</b><br/>&tau;<sub>c</sub> = <b>{sh.tau_c:.3f} N/mm²</b> (Table 19)<br/>&tau;<sub>c,max</sub> = <b>{sh.tau_c_max:.2f} N/mm²</b> (Table 20)", style_math))
        story.append(Paragraph("3.2 Shear Reinforcement", style_h2))
        if sh.needs_shear_reinf:
            story.append(Paragraph(f"&tau;<sub>v</sub> &gt; &tau;<sub>c</sub>, required. Provided: <b>{sh.stirrup_dia:.0f} mm &Oslash;, {sh.legs}-legged @ {sh.spacing:.0f} mm c/c</b>", style_math))
        else:
            story.append(Paragraph(f"&tau;<sub>v</sub> &le; &tau;<sub>c</sub>, nominal only. Provided: <b>{sh.stirrup_dia:.0f} mm &Oslash;, {sh.legs}-legged @ {sh.spacing:.0f} mm c/c</b>", style_math))
        story.append(Spacer(1, 6*mm))

    # 5. SERVICEABILITY CHECK
    if max_step >= 4 and s.serviceability:
        srv = s.serviceability
        story.append(Paragraph("4. SERVICEABILITY CHECK", style_h1))
        story.append(Paragraph(f"Basic Ratio = {srv.basic_ratio}, Mod Factor = {srv.mod_factor:.3f}<br/>Allowable Ratio = <b>{srv.allowable_ratio:.2f}</b>, Actual L/d = <b>{srv.actual_ratio:.2f}</b>", style_math))
        if srv.safe:
            story.append(Paragraph(f"<b><font color='{COLOR_SAFE}'>✓ SAFE IN SERVICEABILITY</font></b>", style_math))
        else:
            story.append(Paragraph(f"<b><font color='{COLOR_FAIL}'>✗ SERVICEABILITY CHECK FAILED</font></b>", style_math))
        story.append(Spacer(1, 6*mm))

    # 6. DETAILING & DRAWING
    if max_step >= 5 and s.detailing:
        det = s.detailing
        bs = s.bar_selection
        cbs = s.comp_bar_selection
        sh = s.shear

        story.append(Paragraph("5. DETAILING CHECK", style_h1))
        det_data = [
            ["Minimum Ast Required (Cl. 26.5.1)", f"Provided {s.get_ast_provided():.1f} ≥ {det.ast_min_req:.1f} mm² — {'OK' if det.min_reinf_ok else 'FAIL'}"],
            ["Maximum Ast Allowed (4% gross)", f"Provided {s.get_ast_provided():.1f} ≤ {det.ast_max_allowed:.1f} mm² — {'OK' if det.max_reinf_ok else 'FAIL'}"],
            ["Minimum Clear Spacing", f"{det.min_clear_spacing:.1f} mm"],
            ["Actual Clear Spacing", f"{det.actual_spacing:.1f} mm — {'OK' if det.spacing_ok else 'FAIL'}" if det.actual_spacing else "N/A (Single Bar)"],
            ["Development Length (Ld)", f"{det.development_length:.1f} mm"],
        ]
        if det.xu_provided is not None:
            det_data.insert(2, ["Neutral Axis of Provided Steel (xu \u2264 xu,max)", f"{det.xu_provided:.1f} \u2264 {det.xu_max:.1f} mm \u2014 {'OK' if det.balanced_ok else 'FAIL'}"])
        det_data.append(["Clear Cover to Links (Cl. 26.4.1)", f"{det.cover_provided:.1f} \u2265 {det.cover_required:.1f} mm \u2014 {'OK' if det.cover_ok else 'FAIL'}"])
        t_det = Table(det_data, colWidths=[70*mm, 60*mm])
        t_det.setStyle(TableStyle([
            ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
            ('FONTWEIGHT', (0,0), (0,-1), 'bold'),
            ('TEXTCOLOR', (0,0), (-1,-1), COLOR_TEXT),
            ('LINEBELOW', (0,0), (-1,-1), 0.5, COLOR_LINE),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ]))
        story.append(t_det)
        story.append(Spacer(1, 8*mm))

        story.append(Paragraph("6. ENGINEERING DRAWINGS", style_h1))

        # --- Helper for Dimensions in ReportLab ---
        def add_rl_dim(d, x1, y1, x2, y2, text, offset=20):
            dx, dy = x2 - x1, y2 - y1
            length = math.hypot(dx, dy)
            if length == 0: return
            nx, ny = dx / length, dy / length
            px, py = -ny, nx
            
            ox1, oy1 = x1 + px * offset, y1 + py * offset
            ox2, oy2 = x2 + px * offset, y2 + py * offset
            
            d.add(Line(x1, y1, ox1 + px*2, oy1 + py*2, strokeColor=c_dim, strokeWidth=0.5))
            d.add(Line(x2, y2, ox2 + px*2, oy2 + py*2, strokeColor=c_dim, strokeWidth=0.5))
            d.add(Line(ox1, oy1, ox2, oy2, strokeColor=c_dim, strokeWidth=0.5))
            
            t_len = 2
            d.add(Line(ox1 - t_len, oy1 - t_len, ox1 + t_len, oy1 + t_len, strokeColor=c_dim))
            d.add(Line(ox2 - t_len, oy2 - t_len, ox2 + t_len, oy2 + t_len, strokeColor=c_dim))
            
            cx, cy = (ox1 + ox2) / 2, (oy1 + oy2) / 2
            g = Group()
            g.add(String(0, 0, text, textAnchor='middle', fontName='Helvetica', fontSize=6, fillColor=COLOR_TEXT))
            g.translate(cx, cy + (2 if px == 0 else 0))
            if dx == 0: g.rotate(90)
            d.add(g)

        # ---------------------------------------------------------
        # ROW 1: Cross Section + Stirrup Detail
        # ---------------------------------------------------------
        r1_w, r1_h = 160*mm, 70*mm
        dr1 = Drawing(r1_w, r1_h)
        
        # Panel 1: Cross Section
        dr1.add(String(0, r1_h - 10, "CROSS SECTION (END VIEW)", fontName='Helvetica-Bold', fontSize=8, fillColor=COLOR_PRIMARY))
        
        c_scale = min(40*mm / s.b, 50*mm / s.D)
        cb_w, cb_h = s.b * c_scale, s.D * c_scale
        cx0, cy0 = 15*mm, 5*mm
        
        dr1.add(Rect(cx0, cy0, cb_w, cb_h, fillColor=c_concrete, strokeColor=COLOR_LINE, strokeWidth=1))
        
        # effective cover is measured to the bar CENTRE, so clear cover to the link depends on the bar dia
        cc_mm = s.effective_cover - 8 - bs.bar_dia / 2
        cc = cc_mm * c_scale
        dr1.add(Rect(cx0 + cc, cy0 + cc, cb_w - 2*cc, cb_h - 2*cc, fillColor=None, strokeColor=c_stirrup, strokeWidth=1, rx=2, ry=2))
        
        tb_r = max((bs.bar_dia / 2) * c_scale, 1.5)
        ty_bot = cy0 + cc + (sh.stirrup_dia * c_scale) + tb_r
        
        for i in range(bs.num_bars):
            tx = cx0 + cc + (sh.stirrup_dia * c_scale) + tb_r + i * ((cb_w - 2*cc - 2*(sh.stirrup_dia*c_scale) - 2*tb_r) / max(1, bs.num_bars - 1)) if bs.num_bars > 1 else cx0 + cb_w/2
            dr1.add(Circle(tx, ty_bot, tb_r, fillColor=c_tens, strokeColor=None))
            
        if cbs:
            cb_r = max((cbs.bar_dia / 2) * c_scale, 1.5)
            ty_top = cy0 + cb_h - cc - (sh.stirrup_dia * c_scale) - cb_r
            for i in range(cbs.num_bars):
                tx = cx0 + cc + (sh.stirrup_dia * c_scale) + cb_r + i * ((cb_w - 2*cc - 2*(sh.stirrup_dia*c_scale) - 2*cb_r) / max(1, cbs.num_bars - 1)) if cbs.num_bars > 1 else cx0 + cb_w/2
                dr1.add(Circle(tx, ty_top, cb_r, fillColor=c_comp, strokeColor=None))

        add_rl_dim(dr1, cx0, cy0+cb_h, cx0+cb_w, cy0+cb_h, f"{int(s.b)}", offset=5)
        add_rl_dim(dr1, cx0, cy0, cx0, cy0+cb_h, f"{int(s.D)}", offset=-5)
        
        # Legend
        lx, ly = cx0 + cb_w + 10*mm, cy0 + cb_h - 5*mm
        if cbs:
            dr1.add(Circle(lx, ly, 1.5, fillColor=c_comp, strokeColor=None))
            dr1.add(String(lx + 3*mm, ly - 1*mm, f"Top Bars: {cbs.num_bars} - {int(cbs.bar_dia)} \u03c6", fontName='Helvetica', fontSize=7, fillColor=COLOR_TEXT))
            ly -= 6*mm
        dr1.add(Circle(lx, ly, 1.5, fillColor=c_tens, strokeColor=None))
        dr1.add(String(lx + 3*mm, ly - 1*mm, f"Bot Bars: {bs.num_bars} - {int(bs.bar_dia)} \u03c6", fontName='Helvetica', fontSize=7, fillColor=COLOR_TEXT))
        ly -= 6*mm
        dr1.add(Line(lx - 2*mm, ly, lx + 2*mm, ly, strokeColor=c_stirrup, strokeWidth=1))
        dr1.add(String(lx + 3*mm, ly - 1*mm, f"Stirrup: {sh.stirrup_dia} \u03c6, 2L", fontName='Helvetica', fontSize=7, fillColor=COLOR_TEXT))
        
        # Panel 2: Stirrup Detail
        sx0 = 100*mm
        dr1.add(String(sx0, r1_h - 10, "STIRRUP DETAIL", fontName='Helvetica-Bold', fontSize=8, fillColor=COLOR_PRIMARY))
        st_w, st_h = (s.b - 2*cc_mm) * c_scale, (s.D - 2*cc_mm) * c_scale
        dr1.add(Rect(sx0, cy0 + cc, st_w, st_h, fillColor=None, strokeColor=c_stirrup, strokeWidth=1.5, rx=2, ry=2))
        dr1.add(Line(sx0 + 3*mm, cy0 + cc + st_h, sx0 + 8*mm, cy0 + cc + st_h - 5*mm, strokeColor=c_stirrup, strokeWidth=1.5))
        dr1.add(Line(sx0, cy0 + cc + st_h - 3*mm, sx0 + 5*mm, cy0 + cc + st_h - 8*mm, strokeColor=c_stirrup, strokeWidth=1.5))
        add_rl_dim(dr1, sx0, cy0+cc+st_h, sx0+st_w, cy0+cc+st_h, f"{int(s.b - 2*cc_mm)}", offset=5)
        add_rl_dim(dr1, sx0+st_w, cy0+cc, sx0+st_w, cy0+cc+st_h, f"{int(s.D - 2*cc_mm)}", offset=5)
        dr1.add(String(sx0 + st_w/2, cy0 - 2*mm, f"135\u00b0 Hook", textAnchor='middle', fontName='Helvetica', fontSize=6, fillColor=COLOR_TEXT))

        story.append(KeepTogether([dr1]))
        story.append(Spacer(1, 5*mm))

        # ---------------------------------------------------------
        # ROW 2: Stirrup Spacing
        # ---------------------------------------------------------
        r2_w, r2_h = 160*mm, 50*mm
        dr2 = Drawing(r2_w, r2_h)
        dr2.add(String(0, r2_h - 10, "STIRRUP SPACING DETAIL (SIDE VIEW)", fontName='Helvetica-Bold', fontSize=8, fillColor=COLOR_PRIMARY))
        
        px0, py0 = 10*mm, 15*mm
        pw, ph = 140*mm, 15*mm
        pscale = pw / (s.span * 1000)
        
        dr2.add(Rect(px0, py0, pw, ph, fillColor=c_concrete, strokeColor=COLOR_LINE, strokeWidth=1))
        dr2.add(PolyLine([px0, py0, px0-3*mm, py0-5*mm, px0+3*mm, py0-5*mm, px0, py0], fillColor=COLOR_LINE, strokeColor=None))
        dr2.add(PolyLine([px0+pw, py0, px0+pw-3*mm, py0-5*mm, px0+pw+3*mm, py0-5*mm, px0+pw, py0], fillColor=COLOR_LINE, strokeColor=None))
        
        z1_e = s.two_zone_shear.zone1_extent if s.beam_type == "Simply Supported" and s.two_zone_shear else 0
        z1_s = s.two_zone_shear.zone1_spacing if s.beam_type == "Simply Supported" and s.two_zone_shear else sh.spacing
        z2_s = s.two_zone_shear.zone2_spacing if s.beam_type == "Simply Supported" and s.two_zone_shear else sh.spacing
        
        def draw_z(start, end, sp):
            curr = start + sp/2
            while curr <= end:
                vx = px0 + curr * pscale
                dr2.add(Line(vx, py0, vx, py0+ph, strokeColor=c_stirrup, strokeWidth=0.5))
                curr += sp
                
        if z1_e > 0:
            draw_z(0, z1_e, z1_s)
            draw_z(z1_e, (s.span*1000)-z1_e, z2_s)
            draw_z((s.span*1000)-z1_e, s.span*1000, z1_s)
            
            dr2.add(String(px0 + (z1_e*pscale)/2, py0+ph+5*mm, f"@{int(z1_s)} c/c", textAnchor='middle', fontName='Helvetica', fontSize=6, fillColor=COLOR_TEXT))
            dr2.add(String(px0 + pw - (z1_e*pscale)/2, py0+ph+5*mm, f"@{int(z1_s)} c/c", textAnchor='middle', fontName='Helvetica', fontSize=6, fillColor=COLOR_TEXT))
            
            add_rl_dim(dr2, px0, py0, px0 + z1_e*pscale, py0, f"2d", offset=-8)
            add_rl_dim(dr2, px0 + z1_e*pscale, py0, px0 + pw - z1_e*pscale, py0, "Mid-span", offset=-8)
            add_rl_dim(dr2, px0 + pw - z1_e*pscale, py0, px0 + pw, py0, f"2d", offset=-8)
        else:
            draw_z(0, s.span*1000, z1_s)
            dr2.add(String(px0 + pw/2, py0+ph+5*mm, f"Uniform Spacing @{int(z1_s)} c/c", textAnchor='middle', fontName='Helvetica', fontSize=6, fillColor=COLOR_TEXT))
            
        add_rl_dim(dr2, px0, py0, px0+pw, py0, f"L = {int(s.span*1000)} mm", offset=-16)

        story.append(KeepTogether([dr2]))
        story.append(Spacer(1, 5*mm))

        # ---------------------------------------------------------
        # ROW 3: Longitudinal Bars
        # ---------------------------------------------------------
        r3_w, r3_h = 160*mm, 50*mm
        dr3 = Drawing(r3_w, r3_h)
        dr3.add(String(0, r3_h - 10, "LONGITUDINAL SECTION", fontName='Helvetica-Bold', fontSize=8, fillColor=COLOR_PRIMARY))
        
        dr3.add(Rect(px0, py0, pw, ph, fillColor=c_concrete, strokeColor=COLOR_LINE, strokeWidth=1))
        dr3.add(PolyLine([px0, py0, px0-3*mm, py0-5*mm, px0+3*mm, py0-5*mm, px0, py0], fillColor=COLOR_LINE, strokeColor=None))
        dr3.add(PolyLine([px0+pw, py0, px0+pw-3*mm, py0-5*mm, px0+pw+3*mm, py0-5*mm, px0+pw, py0], fillColor=COLOR_LINE, strokeColor=None))
        
        bnd = 3*mm
        # Bot Bars
        dr3.add(PolyLine([px0+1.5*mm, py0+2*mm+bnd, px0+1.5*mm, py0+2*mm, px0+pw-1.5*mm, py0+2*mm, px0+pw-1.5*mm, py0+2*mm+bnd], strokeColor=c_tens, strokeWidth=1.5, strokeLineJoin=1))
        dr3.add(String(px0 + pw/2, py0 - 4*mm, f"{bs.num_bars} - {int(bs.bar_dia)} \u03c6 (Bot)", textAnchor='middle', fontName='Helvetica', fontSize=7, fillColor=COLOR_TEXT))
        
        # Top Bars
        if cbs:
            dr3.add(PolyLine([px0+1.5*mm, py0+ph-2*mm-bnd, px0+1.5*mm, py0+ph-2*mm, px0+pw-1.5*mm, py0+ph-2*mm, px0+pw-1.5*mm, py0+ph-2*mm-bnd], strokeColor=c_comp, strokeWidth=1.5, strokeLineJoin=1))
            dr3.add(String(px0 + 20*mm, py0+ph + 2*mm, f"{cbs.num_bars} - {int(cbs.bar_dia)} \u03c6 (Top)", fontName='Helvetica', fontSize=7, fillColor=COLOR_TEXT))
            
        story.append(KeepTogether([dr3]))
        story.append(Spacer(1, 6*mm))

    # ---------------------------------------------------------
    # 7. DETAILED CALCULATION STEPS
    # ---------------------------------------------------------
    if max_step >= 4:
        story.append(Paragraph("7. DETAILED CALCULATION STEPS", style_h1))
        
        # 7.1 Flexural Calculations
        if s.flexural:
            f = s.flexural
            story.append(Paragraph("7.1 Flexural Design (Clause 38)", style_h2))
            xu_ratio = f.xu_max / f.d if f.d else 0
            
            calc_flex = (
                f"<b>1. Effective Depth (d):</b><br/>"
                f"d = D - effective_cover<br/>"
                f"d = {s.D} - {s.effective_cover} = <b>{f.d:.2f} mm</b><br/><br/>"
                
                f"<b>2. Limiting Neutral Axis (x<sub>u,max</sub>):</b><br/>"
                f"x<sub>u,max</sub> = {xu_ratio:.2f} &times; d = {xu_ratio:.2f} &times; {f.d:.2f} = <b>{f.xu_max:.2f} mm</b><br/><br/>"
                
                f"<b>3. Limiting Moment Capacity (M<sub>lim</sub>):</b><br/>"
                f"M<sub>lim</sub> = 0.36 &times; f<sub>ck</sub> &times; b &times; x<sub>u,max</sub> &times; (d - 0.42 &times; x<sub>u,max</sub>) / 10<sup>6</sup><br/>"
                f"M<sub>lim</sub> = 0.36 &times; {f.fck} &times; {s.b} &times; {f.xu_max:.2f} &times; ({f.d:.2f} - 0.42 &times; {f.xu_max:.2f}) / 10<sup>6</sup> = <b>{f.m_lim:.2f} kN&middot;m</b><br/><br/>"
            )
            
            if f.is_singly:
                calc_flex += (
                    f"<b>4. Required Tension Steel (A<sub>st</sub>):</b><br/>"
                    f"A<sub>st</sub> = (0.5 &times; f<sub>ck</sub> / f<sub>y</sub>) &times; [1 - &radic;(1 - 4.6 &times; M<sub>u</sub> &times; 10<sup>6</sup> / (f<sub>ck</sub> &times; b &times; d<sup>2</sup>))] &times; b &times; d<br/>"
                    f"A<sub>st</sub> = (0.5 &times; {f.fck} / {f.fy}) &times; [1 - &radic;(1 - 4.6 &times; {s.mu*1e6:.0f} / ({f.fck} &times; {s.b} &times; {f.d:.2f}<sup>2</sup>))] &times; {s.b} &times; {f.d:.2f}<br/>"
                    f"<b>A<sub>st</sub> = {f.ast:.1f} mm&sup2;</b>"
                )
            else:
                calc_flex += f"<b>4. Required Tension Steel:</b><br/>M<sub>u</sub> ({s.mu:.2f}) &gt; M<sub>lim</sub> ({f.m_lim:.2f}). Section is designed as doubly reinforced."
            
            story.append(Paragraph(calc_flex, ParagraphStyle('MathDetail', parent=style_math, leading=18)))
            story.append(Spacer(1, 6*mm))

        # 7.2 Shear Calculations
        if s.shear:
            sh = s.shear
            story.append(Paragraph("7.2 Shear Design (Clause 40)", style_h2))
            ast_used = s.get_ast_provided()
            
            calc_shear = (
                f"<b>1. Nominal Shear Stress (&tau;<sub>v</sub>):</b><br/>"
                f"&tau;<sub>v</sub> = (V<sub>u</sub> &times; 1000) / (b &times; d)<br/>"
                f"&tau;<sub>v</sub> = ({s.vu} &times; 1000) / ({s.b} &times; {s.flexural.d:.2f}) = <b>{sh.tau_v:.3f} N/mm&sup2;</b><br/><br/>"
                
                f"<b>2. Percentage of Tension Steel (P<sub>t</sub>):</b><br/>"
                f"P<sub>t</sub> = (100 &times; A<sub>st</sub>) / (b &times; d)<br/>"
                f"P<sub>t</sub> = (100 &times; {ast_used:.1f}) / ({s.b} &times; {s.flexural.d:.2f}) = <b>{sh.pt:.3f} %</b><br/><br/>"
                
                f"<b>3. Design Concrete Shear Strength (&tau;<sub>c</sub>):</b><br/>"
                f"Interpolated from IS 456 Table 19 for {s.concrete_grade} and P<sub>t</sub> = {sh.pt:.3f}%<br/>"
                f"<b>&tau;<sub>c</sub> = {sh.tau_c:.3f} N/mm&sup2;</b><br/><br/>"
            )
            
            if sh.needs_shear_reinf:
                calc_shear += (
                    f"<b>4. Shear Reinforcement Spacing (s):</b><br/>"
                    f"V<sub>us</sub> = (&tau;<sub>v</sub> - &tau;<sub>c</sub>) &times; b &times; d / 1000<br/>"
                    f"s = (0.87 &times; f<sub>y</sub> &times; A<sub>sv</sub> &times; d) / (V<sub>us</sub> &times; 1000)<br/>"
                    f"<b>Provided Spacing = {sh.spacing:.0f} mm c/c</b>"
                )
            else:
                 calc_shear += (
                    f"<b>4. Minimum Shear Reinforcement Spacing (s):</b><br/>"
                    f"s = (0.87 &times; f<sub>y</sub> &times; A<sub>sv</sub>) / (0.4 &times; b)<br/>"
                    f"<b>Provided Spacing = {sh.spacing:.0f} mm c/c</b>"
                 )
                 
            story.append(Paragraph(calc_shear, ParagraphStyle('MathDetail', parent=style_math, leading=18)))
            story.append(Spacer(1, 6*mm))

        # 7.3 Serviceability Calculations
        if s.serviceability:
            srv = s.serviceability
            story.append(Paragraph("7.3 Serviceability Check (Clause 23.2)", style_h2))
            
            ast_req, ast_prov, fs_val = srv.ast_required, srv.ast_provided, srv.fs
            
            calc_srv = (
                f"<b>1. Actual Steel Stress (f<sub>s</sub>):</b><br/>"
                f"f<sub>s</sub> = 0.58 &times; f<sub>y</sub> &times; (A<sub>st,req</sub> / A<sub>st,prov</sub>)<br/>"
                f"f<sub>s</sub> = 0.58 &times; {s.flexural.fy} &times; ({ast_req:.1f} / {ast_prov:.1f}) = <b>{fs_val:.2f} N/mm&sup2;</b><br/><br/>"
                
                f"<b>2. Modification Factor (K<sub>t</sub>):</b><br/>"
                f"From a published curve-fit of IS 456 Fig. 4 for f<sub>s</sub> = {fs_val:.2f} and P<sub>t</sub> = {srv.pt:.3f}% (provided steel)<br/>"
                f"<b>K<sub>t</sub> = {srv.mod_factor:.3f}</b><br/><br/>"
                
                f"<b>3. Allowable Span/Depth Ratio:</b><br/>"
                f"Allowable = Basic Ratio &times; K<sub>t</sub> = {srv.basic_ratio:.2f} &times; {srv.mod_factor:.3f} = <b>{srv.allowable_ratio:.2f}</b><br/><br/>"
                
                f"<b>4. Actual Span/Depth Ratio:</b><br/>"
                f"Actual = (Span &times; 1000) / d = ({s.span} &times; 1000) / {s.flexural.d:.2f} = <b>{srv.actual_ratio:.2f}</b>"
            )
            story.append(Paragraph(calc_srv, ParagraphStyle('MathDetail', parent=style_math, leading=18)))
            story.append(Spacer(1, 8*mm))

    # 8. SUMMARY & REPORT
    if max_step >= 6:
        summary_content = []
        summary_content.append(Paragraph("7. SUMMARY & REPORT", style_h1))

        flex_safe = f.is_singly or (s.doubly and s.doubly.safe)
        all_safe = flex_safe and sh.safe and srv.safe and det.all_passed

        sum_data = [
            ["Design Check", "Result", "Requirement", "Status"],
            ["Flexural Design", f"Mu = {s.mu:.1f} kN·m", f"Mlim = {f.m_lim:.1f} kN·m", "SAFE" if flex_safe else "FAIL"],
            ["Shear Design", f"Vu = {s.vu:.1f} kN", f"τv ≤ τc,max", "SAFE" if sh.safe else "FAIL"],
            ["Serviceability", f"L/d = {srv.actual_ratio:.1f}", f"Allowable = {srv.allowable_ratio:.1f}", "SAFE" if srv.safe else "FAIL"],
            ["Detailing", "Per IS 456 Cl. 26", "—", "ADEQUATE" if det.all_passed else "FAIL"]
        ]

        t_sum = Table(sum_data, colWidths=[40*mm, 45*mm, 45*mm, 30*mm])
        t_sum.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), COLOR_CARD),
            ('TEXTCOLOR', (0,0), (-1,0), COLOR_PRIMARY),
            ('TEXTCOLOR', (0,1), (-1,-1), COLOR_TEXT),
            ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('GRID', (0,0), (-1,-1), 0.5, COLOR_LINE),
            ('TEXTCOLOR', (3,1), (3,4), COLOR_SAFE),
        ]))
        
        for i in range(1, 5):
            if "FAIL" in sum_data[i][3]:
                t_sum.setStyle(TableStyle([('TEXTCOLOR', (3,i), (3,i), COLOR_FAIL)]))

        summary_content.append(t_sum)
        summary_content.append(Spacer(1, 6*mm))

        if all_safe:
            summary_content.append(Paragraph(f"OVERALL DESIGN STATUS: <b><font color='{COLOR_SAFE}'>✓ DESIGN ACCEPTABLE</font></b>", style_h2))
        else:
            summary_content.append(Paragraph(f"OVERALL DESIGN STATUS: <b><font color='{COLOR_FAIL}'>✗ DESIGN NOT ACCEPTABLE</font></b>", style_h2))

        summary_content.append(Paragraph("8. FINAL REINFORCEMENT SUMMARY", style_h1))
        
        reinf_txt = f"<b>Beam:</b> {s.b:.0f} &times; {s.D:.0f} mm<br/><br/><b>Bottom (Tension):</b> {bs.num_bars} &times; {bs.bar_dia:.0f} mm &Oslash;<br/>"
        if not f.is_singly and cbs:
            reinf_txt += f"<b>Top (Compression):</b> {cbs.num_bars} &times; {cbs.bar_dia:.0f} mm &Oslash;<br/>"
        
        if s.beam_type == "Simply Supported" and s.two_zone_shear:
            z = s.two_zone_shear
            reinf_txt += f"<br/><b>Stirrups:</b><br/>{sh.stirrup_dia:.0f} mm &Oslash;, {sh.legs}-legged @ {z.zone1_spacing:.0f} mm c/c (within {z.zone1_extent:.0f} mm of supports)<br/>{sh.stirrup_dia:.0f} mm &Oslash;, {sh.legs}-legged @ {z.zone2_spacing:.0f} mm c/c (in remaining mid-span)<br/>"
        else:
            reinf_txt += f"<br/><b>Stirrups:</b> {sh.stirrup_dia:.0f} mm &Oslash;, {sh.legs}-legged @ {sh.spacing:.0f} mm c/c throughout.<br/>"

        reinf_txt += f"<br/><b>Clear Cover to Links:</b> {s.effective_cover - 8 - s.bar_selection.bar_dia / 2:.1f} mm"
        # Wrap the text in a 1-cell Table for perfectly controlled padding and borders
        p_reinf = Paragraph(reinf_txt, ParagraphStyle('Reinf', parent=style_normal, leading=16))
        
        # A4 usable width is 180mm (210mm - 15mm left margin - 15mm right margin)
        t_reinf = Table([[p_reinf]], colWidths=[180*mm])
        t_reinf.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), COLOR_CARD),
            ('BOX', (0,0), (-1,-1), 1, COLOR_LINE),
            ('TOPPADDING', (0,0), (-1,-1), 12),
            ('BOTTOMPADDING', (0,0), (-1,-1), 12),
            ('LEFTPADDING', (0,0), (-1,-1), 12),
            ('RIGHTPADDING', (0,0), (-1,-1), 12),
        ]))
        
        summary_content.append(t_reinf)
        story.append(KeepTogether(summary_content))

    # 9. APPENDIX: IS 456 REFERENCE CHARTS
    if max_step >= 6:
        story.append(Spacer(1, 15*mm))
        story.append(Paragraph("APPENDIX: IS 456 REFERENCE CHARTS", style_h1))
        
        # Figure 4: Modification Factor
        story.append(Paragraph("Fig. 4: Modification Factor for Tension Reinforcement (Cl. 23.2.1)", style_h2))
        story.append(add_reference_image("assets/is456_fig4.png", 150*mm, is_dark))
        story.append(Spacer(1, 10*mm))
        
        # Table 19: Design Shear Strength
        story.append(Paragraph("Table 19: Design Shear Strength of Concrete, τc (Cl. 40.2.1)", style_h2))
        story.append(add_reference_image("assets/is456_table19.png", 150*mm, is_dark))
        story.append(Spacer(1, 10*mm))
        
        # Table 20: Max Shear Stress
        story.append(Paragraph("Table 20: Maximum Shear Stress, τc,max (Cl. 40.2.3)", style_h2))
        story.append(add_reference_image("assets/is456_table20.png", 150*mm, is_dark))
        story.append(Spacer(1, 10*mm))

    # 10. FORMAL SIGN-OFF
    sign_off_content = []
    sign_off_content.append(Spacer(1, 15*mm))
    sign_off_content.append(Paragraph("FORMAL SIGN-OFF", style_h1))
    
    sign_data = [
        ["DESIGN PREPARED BY", "CHECKED BY"],
        ["Name: __________________________", "Name: __________________________"],
        ["Designation: _____________________", "Designation: _____________________"],
        ["Company: _______________________", "Date: ___________________________"],
        ["Date: ___________________________", "Signature: _______________________"],
        ["Signature: _______________________", ""]
    ]
    t_sign = Table(sign_data, colWidths=[85*mm, 85*mm])
    t_sign.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTNAME', (0,1), (-1,-1), 'Helvetica'),
        ('TEXTCOLOR', (0,0), (-1,-1), COLOR_TEXT),
        ('BOTTOMPADDING', (0,0), (-1,-1), 12),
    ]))
    sign_off_content.append(t_sign)
    story.append(KeepTogether(sign_off_content))

    def draw_bg(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(COLOR_BG)
        canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
        canvas.restoreState()

    if is_dark:
        doc.build(story, onFirstPage=draw_bg, onLaterPages=draw_bg)
    else:
        doc.build(story)