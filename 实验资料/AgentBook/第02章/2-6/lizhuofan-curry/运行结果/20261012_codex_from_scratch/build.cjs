// 内容从本次重新读取的论文编写，不读取昨日outline或HTML。
const fs = require('fs');
const path = require('path');
const root = __dirname;
const lab = path.resolve(root, '../..');
const config = JSON.parse(fs.readFileSync(path.join(lab, '工具链配置.json'), 'utf8').replace(/^\uFEFF/, ''));
Object.assign(process.env, config.environment);
const pptxgen = require(path.join(lab, 'node_modules/pptxgenjs'));
const html2pptx = require(path.join(lab, '我的代码/html2pptx_windows.cjs'));
const { chromium } = require(path.join(lab, 'node_modules/playwright'));
const journal = (stage, action, extra={}) => fs.appendFileSync(path.join(root,'disclosure.jsonl'), JSON.stringify({time:new Date().toISOString(),stage,action,...extra})+'\n');
const p = (text, cls='') => `<p${cls ? ` class="${cls}"` : ''}>${text}</p>`;
const bullets = items => `<ul>${items.map(t=>`<li>${t}</li>`).join('')}</ul>`;
const visualManifest = JSON.parse(fs.readFileSync(path.join(root,'source_visuals/manifest.json'),'utf8'));
const figure = (file,x,y,w,h) => {
  const item=visualManifest.visuals.find(v=>v.file.endsWith('/'+file));
  const [iw,ih]=item.image_size, scale=Math.min(w/iw,h/ih), fw=iw*scale, fh=ih*scale;
  return `<img src="../source_visuals/${file}" style="left:${x+(w-fw)/2}pt;top:${y+(h-fh)/2}pt;width:${fw}pt;height:${fh}pt;">`;
};
const area = (html,x=34,y=110,w=650,h=240) => `<div class="area" style="left:${x}pt;top:${y}pt;width:${w}pt;height:${h}pt;">${html}</div>`;
const table = (id,x,y,w,h) => `<div class="placeholder" id="${id}" style="position:absolute;left:${x}pt;top:${y}pt;width:${w}pt;height:${h}pt;"></div>`;
const decks = [
 {title:'Attention Is All You Need', pages:'1', cover:true,
  html:area('<h1 style="font-size:42pt;line-height:1.12;">Attention Is<br>All You Need</h1>'+p('Transformer原论文学习汇报','lead')+p('Vaswani 等 · NIPS 2017','muted')+p('李卓凡 · 2026年10月12日','small'),40,64,640,290),
  notes:'原论文8位作者：Ashish Vaswani、Noam Shazeer、Niki Parmar、Jakob Uszkoreit、Llion Jones、Aidan N. Gomez、Łukasz Kaiser、Illia Polosukhin。论文发表于NIPS 2017，本次文件为arXiv v7，2023年更新。标题和作者见PDF第1页。'},
 {title:'序列建模中的顺序计算', pages:'2',
  html:area(p('研究问题','label')+p('怎样减少循环网络沿序列逐步计算的限制，同时学习远距离依赖？','lead')+bullets(['RNN按位置更新隐藏状态，单个训练样本内难以并行。','Transformer用注意力连接不同位置，保留编码器—解码器框架。','这里的并行主要指训练计算，推理仍逐个生成输出token。'])),
  notes:'PDF第2页Introduction、Background和Model Architecture。最后一点依据原论文自回归解码描述，不把训练并行误写为一次生成全部输出。'},
 {title:'编码器与解码器架构', pages:'3 · Figure 1',
  html:figure('figure1_architecture.png',77,103,171,248)+area(bullets(['编码器与解码器各堆叠6层。','编码器层：自注意力、逐位置前馈网络。','解码器增加掩码自注意力及对编码器输出的交叉注意力。'])+p('原论文采用残差后层归一化：','small')+p('LayerNorm(x + Sublayer(x))','formula'),315,108,368,248),
  notes:'PDF第3页Figure 1与3.1节。图为原始PDF重新渲染裁剪。注意这是2017年模型的Post-LN结构。'},
 {title:'缩放点积注意力', pages:'4 · Figure 2',
  html:figure('figure2_attention.png',35,130,355,154)+area(p('Attention(Q, K, V)','formula')+p('= softmax(QKᵀ / √dₖ)V','formula')+bullets(['Q与K点积得到匹配分数。','缩放后用softmax归一化。','权重对V加权求和。']),421,110,265,235)+area(p('图左为单个注意力计算，图右为多个头的并行计算。','small'),35,304,355,44),
  notes:'PDF第4页式1和Figure 2。维度较大时点积幅度增大，缩放用于避免softmax进入梯度很小的区域。图保持原文件比例。'},
 {title:'多头注意力的维度', pages:'4–5 · §3.2.2',
  html:area(p('同一输入通过不同线性投影，进入多个注意力头。','lead')+p('MultiHead = Concat(head₁, …, headₕ)Wᴼ','formula')+p('Base：d_model = 512，h = 8，dₖ = dᵥ = 64','formula')+bullets(['每个头在不同的表示子空间计算注意力。','拼接各头后再投影，输出仍为512维。','这是原论文Base配置，不是本章Qwen3的16个Query头。'])),
  notes:'PDF第4–5页3.2.2节，最后一句是为本章学习者区分模型配置的解释，不是原论文对Qwen的评价。'},
 {title:'三种注意力的输入与可见范围', pages:'5 · §3.2.3',
  html:table('attention-types',34,112,650,174)+area(p('解码器掩码挡住未来位置；交叉注意力读取编码器已经得到的输入表示。','small'),34,311,650,48),
  native:[['注意力位置','Q来自哪里','K / V来自哪里','可见范围'],['编码器自注意力','编码器当前表示','同一输入序列','全部输入位置'],['解码器自注意力','解码器当前表示','同一输出序列','已知输出位置'],['编码器—解码器','解码器表示','编码器输出','全部输入位置']],
  cols:[2.12,2.08,2.62,2.2], font:15,
  notes:'PDF第5页3.2.3节。这里是中文整理表，表格为可编辑原生对象。掩码与输出右移共同保证预测不读取未知未来输出。'},
 {title:'位置信息与前馈网络', pages:'5–6 · §3.3、§3.5',
  html:area(p('位置编码','label')+p('输入嵌入与同维度的位置编码相加。')+p('PE(pos, 2i) = sin(pos / 10000^(2i/d_model))','small')+p('PE(pos, 2i+1) = cos(pos / 10000^(2i/d_model))','small')+p('逐位置前馈网络','label')+p('FFN(x) = max(0, xW₁ + b₁)W₂ + b₂','formula')+p('Base：512维输入，中间层2048维，输出512维。','small')),
  notes:'PDF第5页3.3节与第6页3.5节。位置编码帮助模型利用位置顺序，不是语言语义的替代。前馈网络在各位置共享同层参数，各层参数不同。'},
 {title:'自注意力的计算代价', pages:'6–7 · Table 1',
  html:figure('table1_complexity.png',34,126,430,73)+area(bullets(['全局自注意力：每层O(n²d)。','顺序操作数和最长路径可为O(1)。','序列很长时，二次复杂度仍是代价。']),490,112,197,231)+area(p('n为序列长度，d为表示维度。论文指出n < d时，自注意力计算上有优势。','small'),34,236,430,80),
  notes:'PDF第6页Table 1和第6–7页Why Self-Attention。表是论文原图。O(1)路径与O(n²d)复杂度描述不同指标，不能混用为恒定计算开销。'},
 {title:'数据与训练设置', pages:'7–8 · §5',
  html:area(bullets(['WMT 2014英德约450万句对，英法约3600万句对。','8张NVIDIA P100：Base约12小时，Big约3.5天。','Adam：β₁=0.9，β₂=0.98，ε=10⁻⁹。','前4000步学习率预热，之后按步数的逆平方根下降。','Base使用dropout 0.1，标签平滑0.1。'])+p('以上为论文训练记录，本次未重新训练Transformer。','small')),
  notes:'PDF第7页5.1–5.3节、第8页5.4节。Base 100000步，Big 300000步。英法Big dropout 0.1，原文另有说明。这里的warmup是训练学习率预热，不是本章服务请求预热。'},
 {title:'机器翻译结果', pages:'8 · Table 2、§6.1',
  html:figure('table2_translation.png',34,120,431,183)+area(p('28.4','metric')+p('Big · 英德BLEU','small')+p('41.8','metric')+p('Big · 英法BLEU，按表2','small'),497,112,189,215)+area(p('表2与摘要给出英法41.8，正文§6.1写41.0；本页保留这处原文不一致。','tiny'),34,326,650,42),
  notes:'PDF第8页Table 2的newstest2014测试结果。Base英德27.3、英法38.1；Big英德28.4、英法41.8。PDF第1页摘要与Table 2一致，但第8页正文6.1写41.0。未自行断定哪个是笔误。FLOPs由论文根据时间、GPU数和估计性能计算，并非本次测量。'},
 {title:'组件变化与开发集表现', pages:'9 · Table 3',
  html:table('ablations',34,110,425,222)+area(bullets(['单头24.9，比Base低0.9 BLEU。','头数增加不保证持续提高。','可学习位置嵌入与正弦方案接近。'])+p('这些是newstest2013开发集结果，不与上一页测试集分数直接比较。','tiny'),487,113,200,234),
  native:[['配置，其他项沿用Base','BLEU(dev)'],['Base，8头','25.8'],['1头','24.9'],['4头','25.5'],['16头','25.8'],['32头','25.4'],['可学习位置嵌入','25.7']],
  cols:[4.4,1.5],font:16,
  notes:'PDF第9页Table 3，选取(A)头数与(E)位置嵌入行制作可编辑摘要表。各头的dk、dv随头数调整以维持计算规模。开发集为newstest2013，不是Table 2的newstest2014。'},
 {title:'注意力中的远距离依赖', pages:'13 · Figure 3',
  html:figure('figure3_dependency.png',34,105,430,206)+area(p('远距离依赖','lead')+bullets(['只展示making位置。','不同颜色代表不同头。','编码器第5层，共6层。']),490,112,197,197)+area(p('原文示例：making … more difficult。注意力图提示关联，不能单凭权重判断因果重要性。','tiny'),34,330,650,33),
  notes:'PDF第13页附录Figure 3。作者描述对making…more difficult的远距离依赖。最后一句为解释边界，不把注意力权重等同于答案因果贡献。图为原始论文裁剪。'},
 {title:'英语成分句法分析', pages:'9–10 · Table 4',
  html:table('parsing',34,114,428,158)+area(p('4层Transformer','lead'),488,110,199,38)+area(p('d_model = 1024'),488,164,199,38)+area(p('WSJ：约4万句。','small'),488,210,199,38)+area(p('半监督：约1700万句。','small'),488,250,199,38)+area(p('评测为WSJ Section 23的F1。不同训练条件分开比较，92.7不是所有表列方法的最高分。','tiny'),34,303,650,45),
  native:[['Transformer训练条件','WSJ 23 F1'],['仅WSJ，有监督','91.3'],['半监督','92.7']],cols:[4.5,1.44],font:18,
  notes:'PDF第9页6.3节、第10页Table 4。这里仅整理Transformer两行，不声称超过表中全部模型：Dyer generative为93.3，Luong multi-task为93.0，条件不同。'},
 {title:'贡献与适用边界', pages:'2、6–10 · §7',
  html:area(p('主要贡献','label')+bullets(['用多头注意力组织编码器—解码器，减少循环计算。','在论文机器翻译任务上取得较高BLEU，并报告较低训练成本。'])+p('需要保留的边界','label')+bullets(['全局注意力随序列长度呈二次复杂度增长。','训练并行不代表自回归推理完全并行。','结果属于论文任务与训练设置，不能直接外推到所有任务。'])),
  notes:'PDF第10页Conclusion，第2页自回归描述和第6页复杂度。论文原图归原作者，本汇报仅用于学习。主要来源：https://arxiv.org/abs/1706.03762。'}
];

const css=`html{background:#fff;}body{width:720pt;height:405pt;margin:0;padding:0;display:flex;position:relative;background:#fff;font-family:Arial,sans-serif;color:#17324d;}*{box-sizing:border-box;}h1{font-size:31pt;line-height:1.18;margin:0;}h2{font-size:21pt;line-height:1.3;margin:0;}p{font-size:18pt;line-height:1.35;margin:0 0 12pt;}ul{font-size:18pt;line-height:1.4;margin:0;padding-left:20pt;}li{margin-bottom:13pt;}img,.area{position:absolute;}img{object-fit:contain;}.label{font-size:16pt;color:#126d87;font-weight:bold;margin:0 0 9pt;}.lead{font-size:22pt;line-height:1.3;}.small{font-size:15pt;line-height:1.45;}.tiny{font-size:13pt;line-height:1.4;}.muted{color:#64748b;font-size:18pt;}.formula{font-size:20pt;line-height:1.35;}.metric{font-size:39pt;color:#126d87;font-weight:bold;line-height:1;margin-bottom:8pt;}.title{position:absolute;left:34pt;top:30pt;width:652pt;height:66pt;}.foot{position:absolute;left:34pt;top:379pt;width:620pt;font-size:10pt;color:#64748b;line-height:1;}.page{position:absolute;left:671pt;top:379pt;font-size:10pt;color:#64748b;line-height:1;}`;

async function main(){
  journal('04_authoring','从原始PDF重新编写14页大纲、HTML和原生表格',{runtime:'当前Codex会话',reused_previous_html:false,paper:'../../材料/attention-is-all-you-need.pdf',workflow:'用户要求的官方PPTX Skill，采用html2pptx而非通用Artifact Tool作者流程'});
  const outline=['# Codex重新生成的论文PPT大纲','','来源：本次重新提取的原始PDF；不读取昨日HTML或大纲。','设计：白底、深蓝文字、青色强调，16:9，论文原图保持比例。',''];
  const pres=new pptxgen();pres.defineLayout({name:'PAPER',width:10,height:5.625});pres.layout='PAPER';pres.author='李卓凡';pres.subject='Transformer原论文学习汇报';pres.title='Attention Is All You Need';pres.lang='zh-CN';
  const browser=await chromium.launch({headless:true});
  const checks=[];
  try{
    for(let i=0;i<decks.length;i++){
      const s=decks[i], name=`slide${String(i+1).padStart(2,'0')}.html`, file=path.join(root,'slides',name);
      const [pageNumbers,sourceLabel]=s.pages.split(' · ');
      const sourceText=`PDF第${pageNumbers}页${sourceLabel ? '，'+sourceLabel : ''}`;
      const html=`<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><style>${css}</style></head><body>${s.cover?'':`<div class="title"><h1>${s.title}</h1></div>`}${s.html}<p class="foot">来源：Vaswani 等，Attention Is All You Need，${sourceText}</p><p class="page">${String(i+1).padStart(2,'0')}</p></body></html>`;
      fs.writeFileSync(file,html,'utf8');outline.push(`## ${i+1}. ${s.title}`,`来源：PDF第${s.pages}页。`,s.notes,'');
      const page=await browser.newPage({viewport:{width:960,height:540}});await page.goto(require('url').pathToFileURL(file).href);
      checks.push(await page.evaluate(()=>({imageFailures:[...document.images].filter(x=>!x.complete||!x.naturalWidth).map(x=>x.src),overflow:document.body.scrollWidth>960||document.body.scrollHeight>540})));await page.close();
      const targetSlide=pres.addSlide();
      const addImage=targetSlide.addImage.bind(targetSlide);
      targetSlide.addImage=options=>{
        // 官方库去掉file://后保留了/E:/和URL编码；只适配本机文件路径。
        if(options.path && /^\/[A-Za-z]:\//.test(options.path)){
          options={...options,path:decodeURIComponent(options.path.slice(1))};
        }
        return addImage(options);
      };
      const {slide,placeholders}=await html2pptx(file,pres,{tmpDir:path.join(root,'tmp_pages'),slide:targetSlide});
      if(s.native){const loc=placeholders[0];const rows=s.native.map((r,index)=>r.map(t=>index===0?{text:t,options:{bold:true,fill:{color:'EDF4F7'},color:'17324D'}}:t));slide.addTable(rows,{...loc,colW:s.cols,fontFace:'Arial',fontSize:s.font,color:'17324D',border:{pt:0.6,color:'CBD5E1'},margin:6,align:'left',valign:'mid',autoPage:false});}
      slide.addNotes(s.notes+'\n论文来源：https://arxiv.org/abs/1706.03762\nPDF版本：1706.03762v7，2023-08-02。');
      const message=`Converted ${i+1}/${decks.length}: ${s.title}`;
      console.log(message);fs.appendFileSync(path.join(root,'build_stdout.log'),message+'\n');
    }
  }finally{await browser.close();}
  fs.writeFileSync(path.join(root,'outline.md'),outline.join('\n'),'utf8');fs.writeFileSync(path.join(root,'html_checks.json'),JSON.stringify(checks,null,2));
  await pres.writeFile({fileName:path.join(root,'presentation.pptx')});
  journal('05_conversion','实际调用未修改的官方html2pptx.js并导出PPTX',{slides:decks.length,official_script:path.join(lab,'skills/pptx/scripts/html2pptx.js'),adapter:path.join(lab,'我的代码/html2pptx_windows.cjs'),output:'presentation.pptx'});
  console.log('CODEX_PPTX_EXPORTED');
}
main().catch(e=>{fs.writeFileSync(path.join(root,'build_error.log'),e.stack||String(e));console.error(e);process.exitCode=1;});
