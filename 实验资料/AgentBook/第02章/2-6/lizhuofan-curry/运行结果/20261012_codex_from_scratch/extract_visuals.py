"""从本次重新渲染的论文页裁剪原图，记录像素坐标和哈希。"""
from pathlib import Path
from PIL import Image
import hashlib
import json

ROOT = Path(__file__).resolve().parent
specs = [
    (3, 'figure1_architecture.png', 'Figure 1', (0.310, 0.080, 0.690, 0.505), [3], 'Transformer编码器与解码器架构'),
    (4, 'figure2_attention.png', 'Figure 2', (0.225, 0.075, 0.780, 0.315), [4], '缩放点积注意力与多头注意力'),
    (6, 'table1_complexity.png', 'Table 1', (0.180, 0.135, 0.820, 0.243), [8], '每层复杂度、顺序操作数和最大路径长度'),
    (8, 'table2_translation.png', 'Table 2', (0.205, 0.118, 0.795, 0.311), [10], '机器翻译BLEU及估算训练计算量'),
    (13, 'figure3_dependency.png', 'Figure 3', (0.185, 0.115, 0.830, 0.385), [12], 'making与远距离依赖的多头注意力'),
]
records = []
for page, name, label, normalized, slides, caption in specs:
    original = ROOT / 'tmp_pages' / f'paper-{page}.png'
    with Image.open(original) as image:
        width, height = image.size
        box = tuple(round(v * (width if i % 2 == 0 else height)) for i, v in enumerate(normalized))
        crop = image.crop(box)
        target = ROOT / 'source_visuals' / name
        crop.save(target)
    records.append(dict(file=f'source_visuals/{name}', pdf_page=page, label=label,
                        caption=caption, slide_numbers=slides, crop_pixels=list(box),
                        rendered_page_size=[width, height], render_dpi=200,
                        image_size=list(crop.size), sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
paper = ROOT.parent.parent / '材料' / 'attention-is-all-you-need.pdf'
(ROOT / 'source_visuals' / 'manifest.json').write_text(
    json.dumps(dict(paper_sha256=hashlib.sha256(paper.read_bytes()).hexdigest(), visuals=records),
               ensure_ascii=False, indent=2), encoding='utf-8')
print('ORIGINAL_VISUALS_EXTRACTED:', len(records))
