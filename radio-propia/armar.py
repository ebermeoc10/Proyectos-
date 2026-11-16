#!/usr/bin/env python3
"""Arma una carpeta Android lista para compilar por cada radio en clientes/<nombre>/.
Cada cliente tiene config.json y, si quiere, logo.png (cuadrado)."""
import json, shutil, sys, pathlib
from PIL import Image, ImageDraw, ImageFont

BASE = pathlib.Path(__file__).parent
OUT = BASE / 'build'

def color(h):
    h = h.lstrip('#'); return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def icono(cfg, logo, n):
    S = n * 4
    im = Image.new('RGBA', (S, S), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=S * 0.22, fill=color(cfg['color']))
    if logo:
        lg = Image.open(logo).convert('RGBA')
        if abs(lg.width - lg.height) < lg.width * 0.1:
            lg = lg.resize((int(S * .78), int(S * .78)), Image.LANCZOS)
            m = Image.new('L', lg.size, 0); ImageDraw.Draw(m).ellipse([0, 0, lg.size[0], lg.size[1]], fill=255)
            im.paste(lg, (int(S * .11), int(S * .11)), m)
        else:
            d.rounded_rectangle([0, 0, S - 1, S - 1], radius=S * 0.22, fill=(255, 255, 255))
            lg.thumbnail((int(S * .96), int(S * .96)), Image.LANCZOS)
            im.paste(lg, ((S - lg.width) // 2, (S - lg.height) // 2), lg)
    else:
        letra = (cfg['nombre'].lower().replace('radio ', '', 1)[:1] or 'r').upper()
        try: f = ImageFont.truetype('DejaVuSans-Bold.ttf', int(S * .55))
        except OSError: f = ImageFont.load_default()
        d.text((S / 2, S / 2), letra, font=f, fill=color(cfg['acento']), anchor='mm')
    return im.resize((n, n), Image.LANCZOS)

def armar(dir_cliente):
    slug = dir_cliente.name
    cfg = json.loads((dir_cliente / 'config.json').read_text(encoding='utf-8'))
    logo = dir_cliente / 'logo.png'
    logo = logo if logo.exists() else None
    dst = OUT / slug
    if dst.exists(): shutil.rmtree(dst)
    shutil.copytree(BASE / 'plantilla' / 'android', dst)
    www = dst / 'app/src/main/assets/www'; www.mkdir(parents=True, exist_ok=True)
    shutil.copy(BASE / 'plantilla/www/index.html', www / 'index.html')
    web = {k: v for k, v in cfg.items() if k not in ('appId', 'version')}
    if logo: shutil.copy(logo, www / 'logo.png'); web['logo'] = 'logo.png'
    (www / 'config.js').write_text('window.RADIO=' + json.dumps(web, ensure_ascii=False) + ';', encoding='utf-8')
    for carpeta, n in [('mdpi', 48), ('hdpi', 72), ('xhdpi', 96), ('xxhdpi', 144), ('xxxhdpi', 192)]:
        p = dst / f'app/src/main/res/mipmap-{carpeta}'; p.mkdir(parents=True, exist_ok=True)
        icono(cfg, logo, n).save(p / 'ic_launcher.png')
    props = lambda v: ''.join(c if ord(c) < 128 else '\\u%04x' % ord(c) for c in str(v))
    with open(dst / 'gradle.properties', 'a') as f:
        f.write(f"\nappName={props(cfg['nombre'])}\nappId={cfg['appId']}\nappVersion={cfg.get('version', 1)}\n")
    print(slug)

if __name__ == '__main__':
    OUT.mkdir(exist_ok=True)
    for c in sorted((BASE / 'clientes').iterdir()):
        if (c / 'config.json').exists(): armar(c)
