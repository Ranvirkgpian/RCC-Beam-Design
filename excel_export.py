import pandas as pd

def export_to_excel(filepath, s):
    """Exports RCC Beam design inputs and results to an Excel file."""
    
    # Check if calculation steps exist before pulling data to avoid NoneType errors
    d_val = s.flexural.d if s.flexural else "N/A"
    ast_req = s.flexural.ast if s.flexural else "N/A"
    tau_v = s.shear.tau_v if s.shear else "N/A"
    stirrup_spacing = s.shear.spacing if s.shear else "N/A"
    
    bot_bars = f"{s.bar_selection.num_bars} - {int(s.bar_selection.bar_dia)} dia" if s.bar_selection else "N/A"
    top_bars = f"{s.comp_bar_selection.num_bars} - {int(s.comp_bar_selection.bar_dia)} dia" if getattr(s, 'comp_bar_selection', None) else "N/A"

    data = {
        "Category": [
            "Geometry", "Geometry", "Geometry", "Geometry", 
            "Material", "Material", 
            "Design Loads", "Design Loads", 
            "Flexural Results", "Flexural Results", 
            "Shear Results", "Shear Results", 
            "Detailing", "Detailing"
        ],
        "Parameter": [
            "Beam Width (b)", "Overall Depth (D)", "Effective Cover", "Span (L)", 
            "Concrete Grade", "Steel Grade", 
            "Factored Moment (Mu)", "Factored Shear (Vu)", 
            "Effective Depth (d)", "Required Tension Steel (Ast)", 
            "Nominal Shear Stress (τv)", "Stirrup Spacing", 
            "Provided Bottom Bars", "Provided Top Bars"
        ],
        "Value": [
            s.b, s.D, s.effective_cover, s.span, 
            s.concrete_grade, s.steel_grade, 
            s.mu, s.vu, 
            d_val, ast_req, 
            tau_v, stirrup_spacing, 
            bot_bars, top_bars
        ],
        "Unit": [
            "mm", "mm", "mm", "m", 
            "-", "-", 
            "kN-m", "kN", 
            "mm", "mm²", 
            "N/mm²", "mm c/c", 
            "-", "-"
        ]
    }

    df = pd.DataFrame(data)
    
    # Save to Excel and auto-adjust column widths
    with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Design Summary')
        worksheet = writer.sheets['Design Summary']
        for column in worksheet.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            worksheet.column_dimensions[column_letter].width = max_length + 2