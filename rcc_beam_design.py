"""
rcc_beam_design.py
IS 456:2000 - RCC Beam design calculation engine (Python port of RccBeamDesign.psm1)
Pure functions: input -> dataclass output, no UI dependencies.

All formulas and lookup tables below were cross-checked directly against the
IS 456:2000 code text (Cl. 38, Cl. 40, Table 19, Table 20, Cl. 23.2, Cl. 26.2.1).
"""

import math
from dataclasses import dataclass
from typing import Optional


# ---------- Lookup tables (verified against IS 456:2000 text) ----------

# Table 19 - Design shear strength of concrete, tau_c (N/mm2), keyed by Pt (%)
TAU_C_TABLE = {
    "M20": {0.15: 0.28, 0.25: 0.36, 0.50: 0.48, 0.75: 0.56, 1.00: 0.62, 1.25: 0.67,
            1.50: 0.72, 1.75: 0.75, 2.00: 0.79, 2.25: 0.81, 2.50: 0.82, 2.75: 0.82, 3.00: 0.82},
    "M25": {0.15: 0.29, 0.25: 0.36, 0.50: 0.49, 0.75: 0.57, 1.00: 0.64, 1.25: 0.70,
            1.50: 0.74, 1.75: 0.78, 2.00: 0.82, 2.25: 0.85, 2.50: 0.88, 2.75: 0.90, 3.00: 0.92},
    "M30": {0.15: 0.29, 0.25: 0.37, 0.50: 0.50, 0.75: 0.59, 1.00: 0.66, 1.25: 0.71,
            1.50: 0.76, 1.75: 0.80, 2.00: 0.84, 2.25: 0.88, 2.50: 0.91, 2.75: 0.94, 3.00: 0.96},
    "M35": {0.15: 0.29, 0.25: 0.37, 0.50: 0.50, 0.75: 0.59, 1.00: 0.67, 1.25: 0.73,
            1.50: 0.78, 1.75: 0.82, 2.00: 0.86, 2.25: 0.90, 2.50: 0.93, 2.75: 0.96, 3.00: 0.99},
    "M40": {0.15: 0.30, 0.25: 0.38, 0.50: 0.51, 0.75: 0.60, 1.00: 0.68, 1.25: 0.74,
            1.50: 0.79, 1.75: 0.84, 2.00: 0.88, 2.25: 0.92, 2.50: 0.95, 2.75: 0.98, 3.00: 1.01},
}

# Table 20 - Max shear stress tau_c,max (N/mm2) - FIXED VALUES, not a formula
TAU_C_MAX_TABLE = {"M20": 2.8, "M25": 3.1, "M30": 3.5, "M35": 3.7, "M40": 4.0}

# fck values by concrete grade
FCK_TABLE = {"M20": 20, "M25": 25, "M30": 30, "M35": 35, "M40": 40}

# fy values by steel grade
FY_TABLE = {"Fe415": 415, "Fe500": 500, "Fe550": 550}

# Design bond stress tau_bd (N/mm2), Cl. 26.2.1.1 - for plain bars in tension
TAU_BD_TABLE = {"M20": 1.2, "M25": 1.4, "M30": 1.5, "M35": 1.7, "M40": 1.9}


# (Older duplicate select_bars/BarSelection removed - see the consolidated
# version below under "Bar selection", which correctly accounts for stirrup
# diameter and aggregate size in the clear spacing check.)


def get_tau_c(pt: float, concrete_grade: str) -> float:
    """Table 19 lookup with linear interpolation between listed Pt values."""
    table = TAU_C_TABLE.get(concrete_grade)
    if table is None:
        raise ValueError(f"Unknown concrete grade: {concrete_grade}")
    keys = sorted(table.keys())
    if pt <= keys[0]:
        return table[keys[0]]
    if pt >= keys[-1]:
        return table[keys[-1]]
    lower = max(k for k in keys if k <= pt)
    upper = min(k for k in keys if k >= pt)
    if lower == upper:
        return table[lower]
    frac = (pt - lower) / (upper - lower)
    return round(table[lower] + frac * (table[upper] - table[lower]), 3)


# ---------- 1. Flexural design (Clause 38) ----------

@dataclass
class FlexuralResult:
    d: float
    fck: float
    fy: float
    xu_max: float
    m_lim: float          # kN.m
    is_singly: bool
    ast: Optional[float]  # mm^2
    ast_min: float
    ast_final: Optional[float]
    safe: bool


def get_flexural_design(b: float, D: float, effective_cover: float, mu: float,
                         concrete_grade: str, steel_grade: str) -> FlexuralResult:
    d = D - effective_cover
    fck = FCK_TABLE.get(concrete_grade)
    fy = FY_TABLE.get(steel_grade)
    if fck is None or fy is None:
        raise ValueError(f"Unknown grade(s): {concrete_grade} / {steel_grade}")

    # 1. Limiting neutral axis depth ratio (Cl. 38.1) - grade dependent, verified
    xu_max_ratio = {415: 0.48, 500: 0.46, 550: 0.44}.get(fy, 0.48)
    xu_max = round(xu_max_ratio * d, 2)

    # 2. Limiting moment capacity
    mlim_nmm = 0.36 * fck * b * xu_max * (d - 0.42 * xu_max)
    mlim = round(mlim_nmm / 1e6, 2)  # kN.m
    mu_nmm = mu * 1e6
    is_singly = mu_nmm <= mlim_nmm

    # 3. Required tension steel (Annex G formula), only if singly reinforced
    ast = None
    if is_singly:
        term = 1 - (4.6 * mu_nmm) / (fck * b * d ** 2)
        term = max(term, 0)
        ast = round((0.5 * fck / fy) * b * d * (1 - math.sqrt(term)), 1)

    # 4. Minimum reinforcement (Cl. 26.5.1.1)
    ast_min = round((0.85 / fy) * b * d, 1)

    ast_final = max(ast, ast_min) if ast is not None else None

    return FlexuralResult(
        d=d, fck=fck, fy=fy, xu_max=xu_max, m_lim=mlim, is_singly=is_singly,
        ast=ast, ast_min=ast_min, ast_final=ast_final, safe=is_singly,
    )


# ---------- Doubly reinforced design (for Mu > Mlim) ----------
# NOTE: Unlike the singly-reinforced formula (which IS 456 Annex G gives as a
# direct equation), doubly reinforced design in the actual code is derived
# from strain-compatibility (Annex G / stress-strain relations), not a single
# closed-form formula. The fsc (compression steel stress) values below are
# standard design-aid values (as published in SP:16 and standard Indian RCC
# textbooks such as Pillai & Menon) commonly used in practice - they are a
# widely accepted approximation of the strain-compatibility solution, not a
# verbatim IS 456 equation. Same caveat status as the deflection modification
# factor elsewhere in this module.

# fsc (N/mm2) vs d'/d ratio - compression steel stress at ultimate limit state
FSC_TABLE_FE415 = {0.05: 355, 0.10: 353, 0.15: 342, 0.20: 329}
FSC_TABLE_FE500 = {0.05: 424, 0.10: 412, 0.15: 395, 0.20: 370}
FSC_TABLE_FE550 = {0.05: 458, 0.10: 441, 0.15: 419, 0.20: 391}  # extrapolated proportionally

FSC_TABLES = {415: FSC_TABLE_FE415, 500: FSC_TABLE_FE500, 550: FSC_TABLE_FE550}


def _interpolate_fsc(d_dash_ratio: float, fy: float) -> float:
    table = FSC_TABLES.get(fy, FSC_TABLE_FE415)
    keys = sorted(table.keys())
    if d_dash_ratio <= keys[0]:
        return table[keys[0]]
    if d_dash_ratio >= keys[-1]:
        return table[keys[-1]]
    lower = max(k for k in keys if k <= d_dash_ratio)
    upper = min(k for k in keys if k >= d_dash_ratio)
    if lower == upper:
        return table[lower]
    frac = (d_dash_ratio - lower) / (upper - lower)
    return table[lower] + frac * (table[upper] - table[lower])


@dataclass
class DoublyReinforcedResult:
    d_dash: float
    ast1: float          # tension steel for the balanced/limiting portion
    ast2: float           # additional tension steel to balance compression steel
    ast_total: float
    asc: float            # compression steel required
    fsc: float             # compression steel stress used (design-aid value)
    ast_min: float
    ast_final: float
    safe: bool


def get_doubly_reinforced_design(b: float, d: float, mu: float, m_lim: float,
                                  xu_max: float, fck: float, fy: float,
                                  d_dash: float = 50.0) -> DoublyReinforcedResult:
    """
    Doubly reinforced beam design for Mu > Mlim.
    d_dash: effective cover to compression steel (mm), typically 40-50mm.
    See module-level note above on fsc table provenance.
    """
    mu_nmm = mu * 1e6
    mlim_nmm = m_lim * 1e6
    mu2_nmm = mu_nmm - mlim_nmm

    # Ast1: tension steel corresponding to the limiting (balanced) moment
    ast1 = mlim_nmm / (0.87 * fy * (d - 0.42 * xu_max))

    d_dash_ratio = d_dash / d
    fsc = _interpolate_fsc(d_dash_ratio, fy)
    fcc = 0.446 * fck  # concrete stress displaced at compression steel level

    # Compression steel required to resist the additional moment Mu2
    asc = mu2_nmm / ((fsc - fcc) * (d - d_dash))

    # Additional tension steel to balance the compression steel force
    ast2 = asc * (fsc - fcc) / (0.87 * fy)

    ast_total = ast1 + ast2
    ast_min = (0.85 / fy) * b * d
    ast_final = max(ast_total, ast_min)

    return DoublyReinforcedResult(
        d_dash=d_dash, ast1=round(ast1, 1), ast2=round(ast2, 1),
        ast_total=round(ast_total, 1), asc=round(asc, 1), fsc=round(fsc, 1),
        ast_min=round(ast_min, 1), ast_final=round(ast_final, 1), safe=True,
    )


# ---------- Bar selection (derives actual bars from required Ast) ----------
# Standard available bar diameters (mm) - IS 1786 standard sizes
STANDARD_BAR_DIAS = [10, 12, 16, 20, 25, 32]

def clear_cover_to_link(effective_cover: float, bar_dia: float, stirrup_dia: float = 8.0) -> float:
    """'Effective cover' is the distance from the outer face to the CENTRE of the tension
    bars (d = D - effective cover). The clear cover to the link is therefore
    effective cover - stirrup dia - bar dia / 2."""
    return effective_cover - stirrup_dia - bar_dia / 2

@dataclass
class BarSelection:
    bar_dia: float
    num_bars: int
    ast_provided: float
    actual_clear_spacing: Optional[float]
    fits: bool
    within_limit: bool = True      # False if Ast,prov exceeds the balanced limit (singly reinforced)


def select_bars(ast_required: float, b: float, clear_cover: float = 25,
                 aggregate_size: float = 20, stirrup_dia: float = 8,
                 min_bars: int = 2, max_bars: int = 8,
                 effective_cover: float = None, max_ast: float = None) -> BarSelection:
    """
    Selects the smallest practical bar diameter/count combination that:
    1. Provides Ast >= ast_required
    2. Fits within the beam width with valid clear spacing (Cl. 26.3.2:
       max(bar dia, aggregate size + 5, 25))
    Prefers fewer, larger bars where practical (closer to Ast_required = less waste),
    but will not choose a spacing-violating arrangement.
    """
    candidates = []
    for dia in STANDARD_BAR_DIAS:
        bar_area = math.pi / 4 * dia ** 2
        for n in range(min_bars, max_bars + 1):
            ast_prov = n * bar_area
            if ast_prov < ast_required:
                continue
            # available width for bars, inside stirrup + clear cover on each side.
            # If effective_cover (to bar CENTRE) is given, the clear cover depends on the bar dia.
            cc = clear_cover_to_link(effective_cover, dia, stirrup_dia) if effective_cover is not None else clear_cover
            avail_width = b - 2 * cc - 2 * stirrup_dia - n * dia
            clear_spacing = avail_width / (n - 1) if n > 1 else None
            min_clear = max(dia, aggregate_size + 5)
            fits = (clear_spacing is None) or (clear_spacing >= min_clear)
            if fits:
                candidates.append(BarSelection(
                    bar_dia=dia, num_bars=n, ast_provided=round(ast_prov, 1),
                    actual_clear_spacing=round(clear_spacing, 1) if clear_spacing else None,
                    fits=True,
                    within_limit=(max_ast is None or ast_prov <= max_ast),
                ))

    # Never prefer an arrangement that exceeds the balanced steel limit (xu > xu,max)
    # when a compliant one exists.
    within = [c for c in candidates if c.within_limit]
    if within:
        candidates = within

    if not candidates:
        # fall back to the best (largest Ast) option even if spacing is tight -
        # caller should flag this for a wider beam or fewer/larger bars
        for dia in STANDARD_BAR_DIAS:
            bar_area = math.pi / 4 * dia ** 2
            for n in range(min_bars, max_bars + 1):
                ast_prov = n * bar_area
                if ast_prov >= ast_required:
                    avail_width = b - 2 * clear_cover - 2 * stirrup_dia - n * dia
                    clear_spacing = avail_width / (n - 1) if n > 1 else None
                    return BarSelection(
                        bar_dia=dia, num_bars=n, ast_provided=round(ast_prov, 1),
                        actual_clear_spacing=round(clear_spacing, 1) if clear_spacing else None,
                        fits=False,
                    )
        raise ValueError("No bar combination could satisfy the required Ast within given limits.")

    # Balance two competing goals: minimal wasted steel (Ast_provided close to
    # Ast_required) vs practical bar count (avoid both "2 huge bars" over-design
    # and "6+ small bars" congestion). Prefer candidates with 3-5 bars first;
    # within that band, pick the one with least excess Ast.
    preferred = [c for c in candidates if 3 <= c.num_bars <= 5]
    pool = preferred if preferred else candidates
    pool.sort(key=lambda c: (c.ast_provided, c.num_bars))
    return pool[0]


# ---------- 2. Shear design (Clause 40) ----------

@dataclass
class ShearResult:
    tau_v: float
    pt: float
    tau_c: float
    tau_c_max: float
    needs_shear_reinf: bool
    stirrup_dia: float
    legs: int
    spacing: Optional[float]
    safe: bool


def get_shear_design(b: float, d: float, vu: float, ast: float, concrete_grade: str,
                      fy_stirrup: float = 415, stirrup_dia: float = 8, legs: int = 2) -> ShearResult:

    # fy_stirrup is capped at 415 N/mm2 by IS 456 Cl. 40.4 and Cl. 26.5.1.6
    fy_stirrup = min(fy_stirrup, 415)
    
    # 1. Nominal shear stress
    tau_v = round((vu * 1000) / (b * d), 3)

    # 2. Percentage of tension steel
    pt = round((ast * 100) / (b * d), 3)

    # 3. Concrete shear strength (Table 19, interpolated - NOT a formula)
    tau_c = get_tau_c(pt, concrete_grade)

    # 4. Max shear stress (Table 20, FIXED value - NOT 0.28*sqrt(fck))
    tau_c_max = TAU_C_MAX_TABLE[concrete_grade]

    needs_shear_reinf = tau_v > tau_c
    is_safe = tau_v <= tau_c_max

    # 5. Stirrup spacing
    asv = legs * math.pi / 4 * stirrup_dia ** 2
    vus = (tau_v - tau_c) * b * d / 1000  # kN, shear resisted by stirrups
    spacing_max = min(0.75 * d, 300)

    if needs_shear_reinf and vus > 0:
        spacing_calc = (fy_stirrup * asv * 0.87 * d) / (vus * 1000)
        spacing = min(math.floor(spacing_calc / 10) * 10, spacing_max)
    else:
        # minimum shear reinforcement spacing (Cl. 26.5.1.6)
        spacing_calc = (0.87 * fy_stirrup * asv) / (0.4 * b)
        spacing = min(math.floor(spacing_calc / 10) * 10, spacing_max)

    return ShearResult(
        tau_v=tau_v, pt=pt, tau_c=tau_c, tau_c_max=tau_c_max,
        needs_shear_reinf=needs_shear_reinf, stirrup_dia=stirrup_dia, legs=legs,
        spacing=spacing, safe=is_safe,
    )


# ---------- Two-zone stirrup spacing (economy detailing) ----------
# NOTE ON ASSUMPTIONS: this app only receives a single factored shear value
# (Vu, typically the maximum, at/near the support) from Beam Input - it does
# not receive a full loading diagram. To split the beam into a "near support"
# zone (higher shear, closer stirrups) and a "mid-span" zone (lower shear,
# wider stirrups), this function assumes the beam is simply supported under a
# uniformly distributed load, for which shear varies LINEARLY from Vu at the
# support to 0 at midspan. This is a standard, common assumption for UDL-
# loaded simply supported beams, but it is an assumption about load type -
# not something IS 456 mandates or that this app can verify from the given
# inputs. If the actual beam has point loads or a different support/loading
# condition, this two-zone split will not be accurate and single-zone
# spacing (get_shear_design) should be used instead.

@dataclass
class TwoZoneShearResult:
    zone1_vu: float          # shear used for near-support zone (at x=2d)
    zone1_spacing: float      # stirrup spacing within 2d of each support
    zone2_vu: float           # shear used for mid-span zone
    zone2_spacing: float      # stirrup spacing beyond 2d (mid-span)
    zone1_extent: float        # physical length of the near-support zone (=2d), mm
    assumption: str


def get_two_zone_shear_design(b: float, d: float, L: float, vu_max: float, ast: float,
                               concrete_grade: str, fy_stirrup: float = 415,
                               stirrup_dia: float = 8, legs: int = 2) -> TwoZoneShearResult:
    """
    Splits stirrup spacing into two zones based on the assumed linear shear
    variation (UDL, simply supported) - see module note above.
    L is span in metres; d, dimensions in mm.
    """
    L_mm = L * 1000
    two_d = 2 * d

    # Shear at x = 2d from support (linear variation: V(x) = Vu_max * (1 - 2x/L))
    zone1_vu = vu_max * max(1 - (2 * two_d / L_mm), 0)
    # Shear at midspan, per the same linear assumption (theoretically 0 for pure UDL,
    # but floor it at a small fraction of Vu_max to avoid an unrealistic zero-shear
    # design in the mid-zone - conservative floor, not a code value)
    zone2_vu = max(vu_max * 0.1, 0)

    zone1 = get_shear_design(b=b, d=d, vu=zone1_vu, ast=ast, concrete_grade=concrete_grade,
                              fy_stirrup=fy_stirrup, stirrup_dia=stirrup_dia, legs=legs)
    zone2 = get_shear_design(b=b, d=d, vu=zone2_vu, ast=ast, concrete_grade=concrete_grade,
                              fy_stirrup=fy_stirrup, stirrup_dia=stirrup_dia, legs=legs)

    return TwoZoneShearResult(
        zone1_vu=round(zone1_vu, 2), zone1_spacing=zone1.spacing,
        zone2_vu=round(zone2_vu, 2), zone2_spacing=zone2.spacing,
        zone1_extent=round(two_d, 1),
        assumption="Linear shear variation assumed (UDL, simply supported beam). "
                   "Not accurate for point loads or other support conditions.",
    )


# ---------- 3. Serviceability (Clause 23.2) ----------
# NOTE: IS 456 Fig. 4 (modification factor for tension reinforcement) is a
# GRAPH in the code, not a closed-form equation. The formula below is a
# widely-used curve-fit approximation of that graph, verified against the
# basic span/depth ratios (7/20/26) which ARE exact code values.
# For final/legal sign-off, cross-check the modification factor against the
# actual Fig. 4 chart rather than relying solely on this approximation.

# Basic span/depth ratios (Cl. 23.2): IS 456 explicitly lists only three
# conditions - Cantilever (7), Simply Supported (20), Continuous (26).
# "Fixed" and "Custom" are NOT explicit IS 456 categories:
# - Fixed (both ends restrained): mapped to the Continuous ratio (26), since
#   both are "beams with restrained ends" in practical terms - this is a
#   standard engineering judgment, not a direct code value.
# - Custom: user-defined support conditions have no single applicable ratio;
#   defaults conservatively to Simply Supported (20) until/unless the user
#   specifies otherwise. This is the most conservative common assumption,
#   not a code-derived value.
BASIC_SPAN_DEPTH_RATIOS = {
    "Cantilever": 7,
    "Simply Supported": 20,
    "Continuous": 26,
    "Fixed": 26,       # judgment call - see note above
    "Custom": 20,       # conservative default - see note above
}


@dataclass
class ServiceabilityResult:
    basic_ratio: float
    mod_factor: float
    allowable_ratio: float
    actual_ratio: float
    safe: bool
    fs: float = 240.0
    span_factor: float = 1.0                 # 10/span for spans above 10 m (Cl. 23.2.1 b)
    needs_deflection_calc: bool = False       # cantilever above 10 m: code requires a deflection calculation
    pt: Optional[float] = None
    ast_required: Optional[float] = None
    ast_provided: Optional[float] = None


def get_serviceability_check(L: float, d: float, pt: float, support_type: str = "Simply Supported",
                              fs: float = None, custom_basic_ratio: float = None,
                              ast_required: float = None, ast_provided: float = None,
                              fy: float = None) -> ServiceabilityResult:
    if custom_basic_ratio is not None:
        basic_ratio = custom_basic_ratio
    else:
        basic_ratio = BASIC_SPAN_DEPTH_RATIOS.get(support_type, 20)

    # Cl. 23.2.1(b): for spans above 10 m the basic values may be multiplied by 10/span (m),
    # except for cantilevers, where a deflection calculation must be made instead.
    span_factor, needs_deflection_calc = 1.0, False
    if custom_basic_ratio is None and L > 10:
        if support_type == "Cantilever":
            needs_deflection_calc = True
        else:
            span_factor = 10.0 / L
            basic_ratio = basic_ratio * span_factor

    if fs is None:
        if ast_required and ast_provided and fy:
            fs = 0.58 * fy * (ast_required / ast_provided)   # IS 456 Fig. 4 note
        else:
            fs = 240.0

    pt_clamped = max(pt, 0.15)
    mf = 1 / (0.225 + 0.00322 * fs - 0.625 * math.log10(pt_clamped))
    mf = round(min(max(mf, 0.5), 2.0), 3)

    allowable_ratio = round(basic_ratio * mf, 2)
    actual_ratio = round((L * 1000) / d, 2)
    is_safe = actual_ratio <= allowable_ratio

    return ServiceabilityResult(
        basic_ratio=basic_ratio, mod_factor=mf, allowable_ratio=allowable_ratio,
        actual_ratio=actual_ratio, safe=is_safe,
        fs=round(fs, 2), pt=round(pt, 3), span_factor=round(span_factor, 3),
        needs_deflection_calc=needs_deflection_calc,
        ast_required=ast_required, ast_provided=ast_provided,
    )


# ---------- 4. Detailing checks (Clause 26) ----------

@dataclass
class DetailingResult:
    ast_min_req: float
    ast_max_allowed: float
    min_reinf_ok: bool
    max_reinf_ok: bool
    min_clear_spacing: float
    actual_spacing: Optional[float]
    spacing_ok: bool
    development_length: float
    all_passed: bool
    cover_provided: Optional[float] = None     # clear cover to links, mm
    cover_required: Optional[float] = None
    cover_ok: bool = True
    xu_provided: Optional[float] = None        # singly reinforced only
    xu_max: Optional[float] = None
    balanced_ok: bool = True


def get_detailing_check(b: float, D: float, d: float, ast: float, ast_provided: float,
                         bar_dia: float, num_bars: int, effective_cover: float,
                         fy: float = 500, concrete_grade: str = "M25",
                         clear_cover: float = 25, aggregate_size: float = 20,
                         stirrup_dia: float = 8, singly_reinforced: bool = False,
                         comp_bar_dia: float = None) -> DetailingResult:
    # Min/max reinforcement (Cl. 26.5.1): max is 4% of GROSS section area (b*D)
    ast_min_req = (0.85 / fy) * b * d
    ast_max_allowed = 0.04 * b * D
    min_ok = ast_provided >= ast_min_req
    max_ok = ast_provided <= ast_max_allowed

    # Clear spacing between bars (Cl. 26.3.2): max(bar dia, aggregate size + 5, 25).
    # Available width accounts for clear cover AND stirrup diameter on each side
    # (bars sit inside the stirrup cage) - this matches select_bars() exactly so
    # the spacing shown here is consistent with what was used to choose the bars.
    min_clear_spacing = max(bar_dia, aggregate_size + 5) 
    # effective_cover is to the bar CENTRE, so the clear cover to the link depends on the bar dia
    cc = clear_cover_to_link(effective_cover, bar_dia, stirrup_dia)
    available_width = b - 2 * cc - 2 * stirrup_dia - num_bars * bar_dia
    actual_spacing = available_width / (num_bars - 1) if num_bars > 1 else None
    spacing_ok = actual_spacing >= min_clear_spacing if actual_spacing is not None else True

    # Development length (Cl. 26.2.1): Ld = (phi * 0.87 * fy) / (4 * tau_bd)
    # deformed bars get +60% bond stress increase
    tau_bd = TAU_BD_TABLE.get(concrete_grade, 1.4) * 1.6
    ld = round((bar_dia * 0.87 * fy) / (4 * tau_bd), 1)

        # Cover (Cl. 26.4.1): nominal cover to the links must not be less than the bar diameter.
    # Durability cover from Table 16 depends on the exposure condition, which is not an input here.
    cover_t = cc
    req_t, prov_t = bar_dia, cover_t
    if comp_bar_dia:
        cover_c = clear_cover_to_link(effective_cover, comp_bar_dia, stirrup_dia)
        if (cover_c - comp_bar_dia) < (cover_t - bar_dia):
            req_t, prov_t = comp_bar_dia, cover_c
    cover_ok = prov_t >= req_t

    # Provided steel must not exceed the balanced limit (xu <= xu,max, Cl. 38.1 / Annex G)
    xu_prov = xu_lim = None
    balanced_ok = True
    if singly_reinforced:
        fck = FCK_TABLE.get(concrete_grade, 25)
        ratio = {415: 0.48, 500: 0.46, 550: 0.44}.get(int(fy), 0.48)
        xu_prov = 0.87 * fy * ast_provided / (0.36 * fck * b)
        xu_lim = ratio * d
        balanced_ok = xu_prov <= xu_lim + 1e-6

    return DetailingResult(
        ast_min_req=round(ast_min_req, 1),
        ast_max_allowed=round(ast_max_allowed, 1),
        min_reinf_ok=min_ok,
        max_reinf_ok=max_ok,
        min_clear_spacing=min_clear_spacing,
        actual_spacing=round(actual_spacing, 1) if actual_spacing is not None else None,
        spacing_ok=spacing_ok,
        development_length=ld,
        all_passed=(min_ok and max_ok and spacing_ok and cover_ok and balanced_ok),
        cover_provided=round(prov_t, 1), cover_required=round(req_t, 1), cover_ok=cover_ok,
        xu_provided=round(xu_prov, 1) if xu_prov is not None else None,
        xu_max=round(xu_lim, 1) if xu_lim is not None else None,
        balanced_ok=balanced_ok,
    )


if __name__ == "__main__":
    # Quick self-check against the same example used to verify the PowerShell module
    flex = get_flexural_design(b=300, D=500, effective_cover=40, mu=180,
                                concrete_grade="M25", steel_grade="Fe500")
    print("Flexural:", flex)

    shear = get_shear_design(b=300, d=flex.d, vu=120, ast=flex.ast_final,
                              concrete_grade="M25")
    print("Shear:", shear)

    service = get_serviceability_check(L=5.0, d=flex.d, pt=shear.pt)
    print("Serviceability:", service)

    detail = get_detailing_check(b=300, D=500, d=flex.d, ast=flex.ast,
                                  ast_provided=1256, bar_dia=20, num_bars=4,
                                  effective_cover=40, fy=500, concrete_grade="M25")
    print("Detailing:", detail)
