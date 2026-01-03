"""创建测试图片"""
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
from pathlib import Path

def create_test_image():
    # 创建 400x200 的图片，浅蓝色背景
    img = Image.new('RGB', (400, 200), color=(230, 240, 255))
    draw = ImageDraw.Draw(img)
    
    # 绘制边框
    draw.rectangle([5, 5, 394, 194], outline=(100, 150, 200), width=3)
    
    # 添加文字
    text1 = "WeChat Automation Test"
    text2 = f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    text3 = "✓ 自动化测试图片"
    
    # 使用默认字体
    draw.text((50, 40), text1, fill=(50, 100, 150))
    draw.text((80, 80), text2, fill=(100, 100, 100))
    draw.text((120, 130), text3, fill=(50, 150, 50))
    
    # 保存
    output_path = Path(__file__).parent / "test_image.png"
    img.save(output_path)
    print(f"测试图片已创建: {output_path}")
    return output_path

if __name__ == "__main__":
    create_test_image()

