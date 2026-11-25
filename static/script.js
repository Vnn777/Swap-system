'use strict';
const ITEMS=JSON.parse(document.querySelector('#app-data').dataset.items);
const TOKEN=document.querySelector('meta[name="csrf-token"]').content;
const $=id=>document.getElementById(id);
let records=[],activeMonth=null,states=ITEMS.map(()=>newState());
const monthFormat=new Intl.DateTimeFormat('pt-BR',{month:'long',year:'numeric',timeZone:'America/Fortaleza'});
const timeFormat=new Intl.DateTimeFormat('pt-BR',{dateStyle:'short',timeStyle:'short',timeZone:'America/Fortaleza'});
const dateInBrazil=iso=>new Date(/(Z|[+-]\d{2}:\d{2})$/.test(iso)?iso:iso+'Z');
function monthKey(iso){const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'America/Fortaleza',year:'numeric',month:'2-digit'}).formatToParts(dateInBrazil(iso));return parts.find(p=>p.type==='year').value+'-'+parts.find(p=>p.type==='month').value;}
function monthName(key){return monthFormat.format(new Date(key+'-15T12:00:00Z'));}
function dateLabel(iso){return timeFormat.format(dateInBrazil(iso));}
function el(tag,cls,txt){const x=document.createElement(tag);if(cls)x.className=cls;if(txt!==undefined)x.textContent=txt;return x;}
function show(name){['library','month','form','detail'].forEach(n=>$(n+'-screen').classList.toggle('hidden',n!==name));window.scrollTo(0,0);}
function notice(id,text,isError=false){const e=$(id);e.textContent=text;e.classList.toggle('error',isError);}
async function api(path,opts={}){const method=opts.method||'GET';const r=await fetch(path,{credentials:'same-origin',...opts,headers:{...(opts.body?{'Content-Type':'application/json'}:{}),...(method!=='GET'?{'X-CSRF-Token':TOKEN}:{}),...opts.headers}});const data=await r.json().catch(()=>({}));if(r.status===401){location.href='/login';throw Error('Sessão encerrada');}if(!r.ok)throw Error(data.error||'Falha ao comunicar com o servidor');return data;}
async function loadArchive(){try{notice('library-feedback','');records=(await api('/api/records')).records;renderArchive();}catch(e){notice('library-feedback',e.message,true);}}
function renderArchive(){
 $('total-count').textContent=records.length;$('pending-count').textContent=records.filter(r=>r.pending_count>0).length;
 const groups=new Map();for(const r of records){const key=monthKey(r.created_at);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(r);}
 $('month-count').textContent=groups.size;
 const root=$('folder-list');root.replaceChildren();
 if(!groups.size){root.append(el('p','empty','Nenhum checklist salvo. Clique em “Criar checklist” para começar.'));return;}
 for(const key of [...groups.keys()].sort().reverse()){
   const items=groups.get(key),btn=el('button','folder'),icon=el('span','folder-icon','▣'),box=el('span','folder-info');
   box.append(el('strong',null,monthName(key)),el('small',null,items.length+' checklist(s) arquivado(s)'));
   btn.append(icon,box,el('span','arrow','→'));btn.type='button';btn.onclick=()=>openMonth(key);root.append(btn);
 }
}
function openMonth(key){activeMonth=key;const subset=records.filter(r=>monthKey(r.created_at)===key);$('month-title').textContent=monthName(key);$('month-subtitle').textContent=subset.length+' checklist(s) salvos nesta pasta';const root=$('month-records');root.replaceChildren();
 for(const r of subset){const btn=el('button','record'),main=el('span','record-info'),date=el('strong',null,r.shift),details=el('small',null,'Salvo em '+dateLabel(r.created_at)+' · Turno de '+r.shift_date.split('-').reverse().join('/'));main.append(date,details);const side=el('span','pill'+(r.pending_count?' warn':''),r.pending_count?r.pending_count+' pendência(s)':'Sem pendências');btn.append(main,side,el('span','arrow','→'));btn.type='button';btn.onclick=()=>openDetail(r.id);root.append(btn);}
 show('month');
}
async function preparePhoto(file) {
 if(!file.type.startsWith('image/'))throw Error('Selecione uma imagem da galeria ou câmera.');
 if(file.size>20*1024*1024)throw Error('Imagem muito grande. Use foto de até 20 MB.');
 let bitmap;
 try { bitmap=await createImageBitmap(file); } catch(e) { throw Error('Não foi possível abrir a foto. Tente uma imagem JPG ou PNG.'); }
 try {
  const scale=Math.min(1,1280/Math.max(bitmap.width,bitmap.height));
  const canvas=document.createElement('canvas');
  canvas.width=Math.max(1,Math.round(bitmap.width*scale));
  canvas.height=Math.max(1,Math.round(bitmap.height*scale));
  canvas.getContext('2d').drawImage(bitmap,0,0,canvas.width,canvas.height);
  let result=canvas.toDataURL('image/jpeg',.72);
  for(const quality of [.60,.46]) {
   if((result.length-23)*.75<=600000)break;
   result=canvas.toDataURL('image/jpeg',quality);
  }
  if((result.length-23)*.75>600000)throw Error('Essa foto ainda ficou grande. Tire uma foto com resolução menor.');
  return result;
 } finally { if(bitmap.close)bitmap.close(); }
}
function newState(){return {active:'ok',note:'',photos:[],line_statuses:{ok:[],pending:[],na:[]}};}
const statusNames={ok:'Conforme',pending:'Pendente',na:'Não aplicável'};
function lineTotal(state){return Object.values(state.line_statuses).reduce((sum,lines)=>sum+lines.length,0);}
function renderItems(){
 const root=$('item-list');root.replaceChildren();
 ITEMS.forEach((title,i)=>{
  const state=states[i];
  const article=el('article','item');article.append(el('span','item-num',i+1));
  const right=el('div','item-body');right.append(el('strong','item-title',title));
  const help=el('p','attachment-help','Selecione uma classificação e marque as linhas correspondentes. Cada linha pode pertencer a apenas uma classificação.');
  right.append(help);
  const options=el('div','options');
  for(const [value,label] of [['ok','Conforme'],['pending','Pendente'],['na','Não aplicável']]){
   const button=el('button','status '+value,label+' ('+state.line_statuses[value].length+')');
   button.type='button';button.setAttribute('aria-pressed',String(state.active===value));
   button.onclick=()=>{state.active=value;renderItems();};
   options.append(button);
  }
  right.append(options);
  const linesWrap=el('div','line-selector');
  const linesTitle=el('div','line-selector-title');
  linesTitle.append(el('strong',null,'Linhas — '+statusNames[state.active]),el('small',null,state.line_statuses[state.active].length+' nesta categoria · '+lineTotal(state)+' de 16 no total'));
  linesWrap.append(linesTitle);
  const lineGrid=el('div','line-grid');
  for(let line=1;line<=16;line++){
   const assigned=Object.keys(state.line_statuses).find(key=>state.line_statuses[key].includes(line));
   const button=el('button','line-btn'+(assigned&&assigned!==state.active?' line-other':''),'Linha '+line);
   button.type='button';
   button.setAttribute('aria-pressed',String(assigned===state.active));
   if(assigned&&assigned!==state.active)button.title='Atualmente em '+statusNames[assigned]+'. Toque para mover.';
   button.setAttribute('aria-label','Linha '+line+(assigned?' — '+statusNames[assigned]:' — não avaliada'));
   button.onclick=()=>{
    if(assigned===state.active){
      state.line_statuses[state.active]=state.line_statuses[state.active].filter(n=>n!==line);
    }else{
      for(const key of Object.keys(state.line_statuses))state.line_statuses[key]=state.line_statuses[key].filter(n=>n!==line);
      state.line_statuses[state.active].push(line);
      state.line_statuses[state.active].sort((a,b)=>a-b);
    }
    renderItems();
   };
   lineGrid.append(button);
  }
  linesWrap.append(lineGrid);
  const allButton=el('button','line-all-btn','Selecionar todas as 16 como '+statusNames[state.active]);
  allButton.type='button';
  allButton.onclick=()=>{
    if(!confirm('Mover todas as 16 linhas para '+statusNames[state.active]+' neste item?'))return;
    for(const key of Object.keys(state.line_statuses))state.line_statuses[key]=key===state.active?Array.from({length:16},(_,n)=>n+1):[];
    renderItems();
  };
  linesWrap.append(allButton);
  const legend=el('p','line-legend','Azul: nesta categoria · Contorno: outra categoria · Branco: ainda não avaliada');
  linesWrap.append(legend);
  right.append(linesWrap);
  if(lineTotal(state)){
   const label=el('label','evidence-label','Relato do ocorrido'+(state.line_statuses.pending.length?' (obrigatório por haver pendências)':' (opcional)'));
   const note=el('textarea','note');note.value=state.note;note.maxLength=500;note.rows=2;
   note.placeholder=state.line_statuses.pending.length?'Descreva as pendências e linhas afetadas':'Descreva o que foi conferido';
   note.setAttribute('aria-label','Relato do item '+(i+1));note.oninput=e=>{state.note=e.target.value;};
   label.append(note);right.append(label);
   const photoWrap=el('div','photo-attachment');
   photoWrap.append(el('strong','attachment-heading','📷 Anexo de Fotos'));
   photoWrap.append(el('p','attachment-help','Até 2 fotos por verificação, independentemente da classificação. Identifique a linha no relato.'));
   const gallery=el('div','photo-previews');
   for(const [n,src] of state.photos.entries()){
    const tile=el('div','photo-preview'),img=el('img');
    img.src=src;img.alt='Foto anexada '+(n+1)+' ao item '+(i+1);img.loading='lazy';
    const remove=el('button','remove-photo','Remover');remove.type='button';remove.onclick=()=>{state.photos.splice(n,1);renderItems();};
    tile.append(img,remove);gallery.append(tile);
   }
   photoWrap.append(gallery);
   const input=el('input','photo-input');input.type='file';input.accept='image/*';input.multiple=true;input.setAttribute('aria-label','Anexar fotos ao item '+(i+1));
   input.onchange=async e=>{
    const files=Array.from(e.target.files||[]);
    if(files.length+state.photos.length>2){alert('Você pode anexar no máximo 2 fotos por verificação.');return;}
    try{const imageData=[];for(const file of files)imageData.push(await preparePhoto(file));state.photos.push(...imageData);renderItems();}
    catch(err){alert(err.message);input.value='';}
   };
   if(state.photos.length<2)photoWrap.append(input);
   right.append(photoWrap);
  }
  article.append(right);root.append(article);
 });
 $('progress').textContent=states.filter(s=>lineTotal(s)>0).length+' de 9 avaliados';
}
function openForm(){$('checklist-form').reset();const now=new Date();$('date').value=now.getFullYear()+'-'+String(now.getMonth()+1).padStart(2,'0')+'-'+String(now.getDate()).padStart(2,'0');states=ITEMS.map(()=>newState());notice('save-feedback','');renderItems();show('form');}
$('checklist-form').onsubmit=async e=>{e.preventDefault();const payload={date:$('date').value,shift:$('shift').value,outgoing:$('outgoing').value,notes:$('notes').value,items:states};const btn=$('save-btn');btn.disabled=true;try{const result=await api('/api/records',{method:'POST',body:JSON.stringify(payload)});await loadArchive();show('library');notice('library-feedback','Checklist #'+result.id+' salvo com sucesso! Abra a pasta do mês para consultá-lo.');}catch(err){notice('save-feedback',err.message,true);}finally{btn.disabled=false;}};
async function openDetail(id){try{const result=await api('/api/records/'+id);const r=result.record;const root=$('detail-content');root.replaceChildren();$('detail-title').textContent='Checklist #'+r.id;$('detail-datetime').textContent='Salvo em '+dateLabel(r.created_at);
const grid=el('div','detail-grid');for(const [label,value] of [['Data do turno',r.shift_date.split('-').reverse().join('/')],['Turno',r.shift],['Responsável pela Vistoria da Linha',r.outgoing]]){const field=el('div','detail-field');field.append(el('small',null,label),el('strong',null,value));grid.append(field);}root.append(grid,el('h2',null,'Itens verificados'));const list=el('ol','detail-items');for(const item of result.items){const li=el('li');li.append(el('strong',null,ITEMS[item.item_number-1]));
 const groups=item.line_statuses||{ok:[],pending:[],na:[]};
 for(const status of ['ok','pending','na']){
  const lines=groups[status]||[];
  if(!lines.length)continue;
  const summary=el('div','detail-status-line');
  summary.append(el('span','pill'+(status==='pending'?' warn':''),statusNames[status]),el('p','evaluated-lines',lines.map(n=>'Linha '+n).join(' · ')));
  li.append(summary);
 }
 if(!Object.values(groups).some(x=>x.length))li.append(el('p','evaluated-lines','Registro antigo: linhas não especificadas'));if(item.note)li.append(el('p','muted',item.note));
if(item.photos&&item.photos.length){
 const photos=el('div','archived-photos');
 for(const photo of item.photos){
  const link=el('a','archived-photo');link.href=photo.url;link.target='_blank';link.rel='noopener';
  const image=el('img');image.src=photo.url;image.alt='Foto de evidência do item '+item.item_number;image.loading='lazy';
  link.append(image);photos.append(link);
 }
 li.append(photos);
}
list.append(li);}root.append(list,el('h2',null,'Observações gerais'),el('p','muted',r.notes||'Nenhuma'));show('detail');}catch(e){alert(e.message);}}
$('new-btn').onclick=openForm;$('new-from-month').onclick=openForm;$('back-library').onclick=()=>show('library');$('back-form').onclick=()=>{if(confirm('Descartar o checklist ainda não salvo?'))show('library');};$('cancel-btn').onclick=$('back-form').onclick;$('back-detail').onclick=()=>activeMonth?openMonth(activeMonth):show('library');$('print-btn').onclick=()=>window.print();$('logout').onclick=async()=>{try{await api('/logout',{method:'POST'});location.href='/login';}catch(e){alert(e.message);}};loadArchive();
