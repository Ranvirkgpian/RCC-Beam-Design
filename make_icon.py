import os
from PIL import Image, ImageDraw

def create_file_icon():
    # Create a transparent 256x256 canvas
    size = 256
    img = Image.new('RGBA', (size, size), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)

    # 1. Draw the document base (Dark blue-gray matching your UI)
    draw.rounded_rectangle([32, 24, 224, 232], radius=12, fill="#1E293B", outline="#3B82F6", width=8)

    # 2. Draw a folded document corner in the top right
    draw.polygon([(168, 24), (224, 80), (168, 80)], fill="#3B82F6")

    # 3. Draw a concrete beam in the middle of the document
    draw.rectangle([64, 110, 192, 155], fill="#94A3B8", outline="#CBD5E1", width=4)

    # 4. Draw the red tension rebar inside the beam
    draw.line([72, 142, 184, 142], fill="#EF4444", width=6)
    draw.ellipse([72-4, 142-4, 72+4, 142+4], fill="#EF4444")
    draw.ellipse([184-4, 142-4, 184+4, 142+4], fill="#EF4444")

    # Save as a multi-size Windows icon
    os.makedirs('assets', exist_ok=True)
    icon_path = 'assets/rccbeam_file.ico'
    img.save(icon_path, format='ICO', sizes=[(256, 256), (128, 128), (64, 64), (32, 32)])
    print(f"Success! Custom icon saved to: {os.path.abspath(icon_path)}")

if __name__ == "__main__":
    create_file_icon()