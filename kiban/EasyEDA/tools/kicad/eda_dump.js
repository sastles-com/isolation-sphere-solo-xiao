// 【出典】FPC-isolation-sphere/kiban/resized/power-2S-02/tools/eda-dump-full.js（2026-08-11）。
// tools/kicad/kicad_export.py が、ページを開いて保存したあとに実行する。
// 回路図の全要素を KiCad 生成用に構造化して吐き出す (読み取り専用)
const g=(o,n)=>(o&&typeof o['getState_'+n]==='function'?o['getState_'+n]():undefined);
const flat=(L)=>{const r=[];const walk=(a)=>{for(const v of a) Array.isArray(v)?walk(v):r.push(v);};walk(L||[]);return r;};
const R=(v)=>Math.round(v*1000)/1000;

const proj=await eda.dmt_Project.getCurrentProjectInfo();
const doc=await eda.dmt_SelectControl.getCurrentDocumentInfo();

const comps=(await eda.sch_PrimitiveComponent.getAll())||[];
const parts=[], netports=[], netflags=[], others=[];
for(const c of comps){
  const t=g(c,'ComponentType');
  const base={type:t, des:g(c,'Designator')||null, x:R(g(c,'X')), y:R(g(c,'Y')),
    rot:g(c,'Rotation')||0, mirror:!!g(c,'Mirror'), net:g(c,'Net')||null};
  if(t==='sheet'){ others.push(base); continue; }
  const ps=(await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(g(c,'PrimitiveId')))||[];
  base.pins=ps.map(p=>({num:g(p,'PinNumber')||null, name:g(p,'PinName')||null, x:R(g(p,'X')), y:R(g(p,'Y'))}));
  if(t==='part'){
    base.value=g(c,'Name'); base.lcsc=g(c,'SupplierId'); base.mpn=g(c,'ManufacturerId');
    const lib=g(c,'Component')||{}; base.libUuid=lib.libraryUuid||null; base.symUuid=lib.uuid||null;
    parts.push(base);
  } else if(t==='netport') netports.push(base);
  else if(t==='netflag') netflags.push(base);
  else others.push(base);
}
const wires=[];
for(const w of (await eda.sch_PrimitiveWire.getAll())||[]){
  const p=flat(g(w,'Line')); const pts=[];
  for(let i=0;i<p.length;i+=2) pts.push([R(p[i]),R(p[i+1])]);
  wires.push({net:String(g(w,'Net')||''), pts});
}
const rects=((await eda.sch_PrimitiveRectangle.getAll())||[]).map(r=>({
  x:R(g(r,'TopLeftX')), yRead:R(g(r,'TopLeftY')), topY:R(-g(r,'TopLeftY')),
  w:R(g(r,'Width')), h:R(g(r,'Height')), color:g(r,'Color'), lineType:g(r,'LineType')}));
const texts=((await eda.sch_PrimitiveText.getAll())||[]).map(t=>({
  content:g(t,'Content'), x:R(g(t,'X')), y:R(g(t,'Y')), size:g(t,'FontSize'),
  bold:!!g(t,'Bold'), rot:g(t,'Rotation')||0, align:g(t,'AlignMode')}));

return {project:{uuid:proj&&proj.uuid, name:proj&&proj.friendlyName},
  doc:{uuid:doc&&doc.uuid, parentProjectUuid:doc&&doc.parentProjectUuid},
  parts, netports, netflags, others, wires, rects, texts,
  counts:{parts:parts.length, netports:netports.length, netflags:netflags.length,
          wires:wires.length, rects:rects.length, texts:texts.length}};
