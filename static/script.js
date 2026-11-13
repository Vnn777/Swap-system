'use strict';
const ITEMS=JSON.parse(document.querySelector('#app-data').dataset.items);
const TOKEN=document.querySelector('meta[name="csrf-token"]').content;
const $=id=>document.getElementById(id);
let records=[],activeMonth=null,states=ITEMS.map(()=>({status:'',note:'',photos:[]}));
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
 for(const r of subset){const btn=el('button','record'),main=el('span','record-info'),date=el('strong',null,r.sector+' · '+r.shift),details=el('small',null,'Salvo em '+dateLabel(r.created_at)+' · Turno de '+r.shift_date.split('-').reverse().join('/'));main.append(date,details);const side=el('span','pill'+(r.pending_count?' warn':''),r.pending_count?r.pending_count+' pendência(s)':'Sem pendências');btn.append(main,side,el('span','arrow','→'));btn.type='button';btn.onclick=()=>openDetail(r.id);root.append(btn);}
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
function renderItems(){
 const root=$('item-list');root.replaceChildren();
 ITEMS.forEach((title,i)=>{
  const article=el('article','item');article.append(el('span','item-num',i+1));
  const right=el('div','item-body');right.append(el('strong','item-title',title));
  const options=el('div','options');
  for(const [value,label] of [['ok','Conforme'],['pending','Pendente'],['na','Não aplicável']]){
   const button=el('button','status '+value,label);
   button.type='button';button.setAttribute('aria-pressed',String(states[i].status===value));
   button.onclick=()=>{
    states[i].status=value;
    if(value==='ok'){states[i].note='';states[i].photos=[];}
    renderItems();
   };options.append(button);
  }
  right.append(options);
  if(states[i].status==='pending'||states[i].status==='na'){
   const label=el('label','evidence-label','Relato do ocorrido');
   const note=el('textarea','note');note.value=states[i].note;note.maxLength=500;note.rows=2;
   note.placeholder=states[i].status==='pending'?'Descreva a pendência e o que foi observado':'Explique por que esse item não se aplica';
   note.setAttribute('aria-label','Relato do item '+(i+1));note.oninput=e=>{states[i].note=e.target.value;};
   label.append(note);right.append(label);
   const photoWrap=el('div','photo-attachment');
   photoWrap.append(el('strong','attachment-heading','📷 Anexo de Fotos'));
   photoWrap.append(el('p','attachment-help','Adicione até 2 fotos para comprovar o relato. Aceita imagens da câmera ou galeria.'));
   const gallery=el('div','photo-previews');
   for(const [n,src] of states[i].photos.entries()){
    const tile=el('div','photo-preview');const img=el('img');img.src=src;img.alt='Foto anexada '+(n+1)+' ao item '+(i+1);img.loading='lazy';
    const remove=el('button','remove-photo','Remover');remove.type='button';remove.setAttribute('aria-label','Remover foto '+(n+1));
    remove.onclick=()=>{states[i].photos.splice(n,1);renderItems();};
    tile.append(img,remove);gallery.append(tile);
   }
   photoWrap.append(gallery);
   const input=el('input','photo-input');input.type='file';input.accept='image/*';input.multiple=true;
   input.setAttribute('aria-label','Anexar fotos ao item '+(i+1));
   input.onchange=async e=>{
    const files=Array.from(e.target.files||[]);
    if(files.length+states[i].photos.length>2){alert('Você pode anexar no máximo 2 fotos por item.');return;}
    try{
     const imageData=[];
     for(const file of files)imageData.push(await preparePhoto(file));
     states[i].photos.push(...imageData);
     renderItems();
    }catch(err){alert(err.message);input.value='';}
   };
   if(states[i].photos.length<2)photoWrap.append(input);
   right.append(photoWrap);
  }
  article.append(right);root.append(article);
 });
 $('progress').textContent=states.filter(s=>s.status).length+' de 9 avaliados';
}
function openForm(){$('checklist-form').reset();const now=new Date();$('date').value=now.getFullYear()+'-'+String(now.getMonth()+1).padStart(2,'0')+'-'+String(now.getDate()).padStart(2,'0');states=ITEMS.map(()=>({status:'',note:'',photos:[]}));notice('save-feedback','');renderItems();show('form');}
$('checklist-form').onsubmit=async e=>{e.preventDefault();const payload={date:$('date').value,shift:$('shift').value,outgoing:$('outgoing').value,incoming:$('incoming').value,sector:$('sector').value,notes:$('notes').value,items:states};const btn=$('save-btn');btn.disabled=true;try{const result=await api('/api/records',{method:'POST',body:JSON.stringify(payload)});await loadArchive();show('library');notice('library-feedback','Checklist #'+result.id+' salvo com sucesso! Abra a pasta do mês para consultá-lo.');}catch(err){notice('save-feedback',err.message,true);}finally{btn.disabled=false;}};
async function openDetail(id){try{const result=await api('/api/records/'+id);const r=result.record;const root=$('detail-content');root.replaceChildren();$('detail-title').textContent='Checklist #'+r.id;$('detail-datetime').textContent='Salvo em '+dateLabel(r.created_at);
const grid=el('div','detail-grid');for(const [label,value] of [['Data do turno',r.shift_date.split('-').reverse().join('/')],['Turno',r.shift],['Setor/Linha',r.sector],['Responsável pela Vistoria da Linha',r.outgoing],['Responsáveis ou Líder da Linha',r.incoming]]){const field=el('div','detail-field');field.append(el('small',null,label),el('strong',null,value));grid.append(field);}root.append(grid,el('h2',null,'Itens verificados'));const list=el('ol','detail-items');for(const item of result.items){const li=el('li');li.append(el('strong',null,ITEMS[item.item_number-1]),el('span','pill'+(item.status==='pending'?' warn':''),({ok:'Conforme',pending:'Pendente',na:'Não aplicável'})[item.status]));if(item.note)li.append(el('p','muted',item.note));
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
