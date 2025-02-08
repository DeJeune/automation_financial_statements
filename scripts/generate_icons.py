#!/usr/bin/env python3
import os
from pathlib import Path
from PIL import Image
import cairosvg


def ensure_dir(path):
    """确保目录存在"""
    os.makedirs(path, exist_ok=True)


def svg_to_png(svg_path, png_path, size):
    """将 SVG 转换为指定大小的 PNG"""
    cairosvg.svg2png(url=str(svg_path), write_to=str(
        png_path), output_width=size, output_height=size)


def create_ico(png_paths, ico_path):
    """创建 Windows ICO 文件"""
    images = []
    for png_path in png_paths:
        img = Image.open(png_path)
        images.append(img)

    # 保存为 ICO，包含多个尺寸
    images[0].save(ico_path, format='ICO', sizes=[
                   (img.width, img.height) for img in images])


def create_icns(png_paths, icns_path):
    """创建 macOS ICNS 文件"""
    iconset_path = Path(icns_path).parent / 'app.iconset'
    ensure_dir(iconset_path)

    # macOS 图标尺寸命名约定
    size_names = {
        16: '16x16',
        32: '32x32',
        64: '64x64',
        128: '128x128',
        256: '256x256',
        512: '512x512',
        1024: '1024x1024'
    }

    for png_path in png_paths:
        size = Image.open(png_path).width
        if size in size_names:
            name = f'icon_{size_names[size]}.png'
            name2x = f'icon_{size_names[size//2]}@2x.png' if size//2 in size_names else None

            # 复制到 iconset
            os.system(f'cp "{png_path}" "{iconset_path}/{name}"')
            if name2x:
                os.system(f'cp "{png_path}" "{iconset_path}/{name2x}"')

    # 使用 iconutil 创建 icns（仅在 macOS 上可用）
    os.system(f'iconutil -c icns "{iconset_path}" -o "{icns_path}"')


def main():
    # 设置路径
    root_dir = Path(__file__).parent.parent
    assets_dir = root_dir / 'assets'
    temp_dir = assets_dir / 'temp'
    ensure_dir(temp_dir)

    svg_path = assets_dir / 'python-logo.svg'
    ico_path = assets_dir / 'app.ico'
    icns_path = assets_dir / 'app.icns'

    # 需要的尺寸
    sizes = [16, 32, 64, 128, 256, 512, 1024]
    png_paths = []

    # 生成不同尺寸的 PNG
    for size in sizes:
        png_path = temp_dir / f'icon_{size}.png'
        svg_to_png(svg_path, png_path, size)
        png_paths.append(png_path)

    # 创建 ICO 和 ICNS
    create_ico(png_paths, ico_path)
    if os.system('which iconutil') == 0:  # 仅在 macOS 上创建 ICNS
        create_icns(png_paths, icns_path)

    # 清理临时文件
    for png_path in png_paths:
        os.remove(png_path)
    if os.path.exists(temp_dir):
        os.rmdir(temp_dir)


if __name__ == '__main__':
    main()
