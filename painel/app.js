(function(){
const RAW=/*__DADOS__*/[];
const XP=/*__XP__*/null;
const INV=/*__INTERINV__*/null;
const SYNC=/*__SYNC__*/null;
const IND=/*__INDICES__*/null;
const RADAR=/*__RADAR__*/null;
const REVISAR=/*__REVISAR__*/[];
const DEMO=/*__DEMO__*/false;  // true só na demonstração pública (scripts/gerar_demo.py)
const MES=['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez'];
const MES_L=['janeiro','fevereiro','março','abril','maio','junho','julho','agosto','setembro','outubro','novembro','dezembro'];
const DOW=['domingo','segunda','terça','quarta','quinta','sexta','sábado'];
const brl=new Intl.NumberFormat('pt-BR',{style:'currency',currency:'BRL'});
const fmt=v=>brl.format(v);
const fmtK=v=>Math.abs(v)>=1000?'R$ '+(v/1000).toLocaleString('pt-BR',{maximumFractionDigits:1})+' mil':brl.format(Math.round(v));
const pct=v=>(v*100).toLocaleString('pt-BR',{maximumFractionDigits:1})+'%';
const cap=s=>s[0].toUpperCase()+s.slice(1);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const pctN=(v,d=2)=>v==null?'—':v.toLocaleString('pt-BR',{maximumFractionDigits:d,minimumFractionDigits:d?Math.min(d,2):0})+'%';
const sgn=v=>(v>=0?'+':'−')+fmt(Math.abs(v));
const cl=v=>v>=0?'pos':'neg';
const dmY=s=>s.split('-').reverse().join('/');
const mesAno=s=>MES[+s.slice(5,7)-1]+'/'+s.slice(2,4);

/* ---------- dados ---------- */
const tx=RAW.map(([d,desc,cat,type,v,tit,acc,prod,mot])=>({d:new Date(d+'T12:00:00'),ds:d,desc,cat,type,v,tit,acc,prod:prod||'',mot:mot||''}))
  .sort((a,b)=>b.d-a.d||b.v-a.v);
const HOJE=tx.length?tx[0].d:new Date();
const PRIMEIRO=tx.length?tx[tx.length-1].d:new Date();
const YEARS=[...new Set(tx.map(t=>t.d.getFullYear()))].sort((a,b)=>b-a);
const monthsOf={};tx.forEach(t=>{(monthsOf[t.d.getFullYear()]??=new Set()).add(t.d.getMonth())});
const firstMonth=y=>Math.min(...monthsOf[y]);
const lastMonth=y=>Math.max(...monthsOf[y]);
const monthRange=y=>{const a=[];for(let m=firstMonth(y);m<=lastMonth(y);m++)a.push(m);return a};
const cats=[...new Set(tx.filter(t=>t.type==='saida'||t.cat==='Investimentos').map(t=>t.cat))].sort((a,b)=>a.localeCompare(b,'pt-BR'));
const isXP=t=>t.prod==='XP';
const isDelivery=t=>/ifood|ifd\*|99 ?food/i.test(t.desc);

/* ---------- estado ---------- */
const S={year:YEARS[0],month:'all',acc:'all',cat:'all',q:'',day:null,limit:15};
function sel(o={}){
  const f={...S,...o};
  return tx.filter(t=>t.d.getFullYear()===f.year&&(f.month==='all'||t.d.getMonth()===f.month)&&(f.acc==='all'||t.acc===f.acc)&&(f.cat==='all'||t.cat===f.cat)&&(!f.day||t.d.getDate()===f.day)&&(!f.q||t.desc.toLowerCase().includes(f.q)));
}
const base=o=>sel({q:'',day:null,...o});
function sums(list){const s={in:0,out:0,inv:0,res:0};for(const t of list){if(t.type==='entrada')s.in+=t.v;else if(t.type==='saida')s.out+=t.v;else if(t.type==='aporte')s.inv+=t.v;else if(t.type==='resgate')s.res+=t.v}return s}
function prevPeriod(){
  if(S.month!=='all'){
    let y=S.year,m=S.month-1;if(m<0){m=11;y--}
    if(!monthsOf[y]||!monthsOf[y].has(m))return null;
    return {list:base({year:y,month:m}),label:MES[m].toLowerCase()+'/'+y};
  }
  const py=S.year-1;if(!monthsOf[py])return null;
  const lm=lastMonth(S.year),fm=firstMonth(S.year);
  if(firstMonth(py)>fm)return null; // ano anterior incompleto
  return {list:base({year:py}).filter(t=>t.d.getMonth()>=fm&&t.d.getMonth()<=lm),label:py+(lm<11||fm>0?` (${MES[fm].toLowerCase()}–${MES[lm].toLowerCase()})`:'')};
}
function periodLabel(){return S.month==='all'?String(S.year):MES_L[S.month]+' de '+S.year}

/* ---------- filtros ---------- */
const $=id=>document.getElementById(id);
$('f-year').innerHTML=YEARS.map(y=>`<option value="${y}">${y}</option>`).join('');
function drawFilters(){
  const has=monthsOf[S.year];
  $('f-month').innerHTML=['all',...MES.keys()].map(m=>`<option value="${m}" ${S.month===m?'selected':''} ${m!=='all'&&!has.has(m)?'disabled':''}>${m==='all'?'Ano todo':MES_L[m][0].toUpperCase()+MES_L[m].slice(1)}</option>`).join('');
  $('f-tab').querySelectorAll('button').forEach(b=>{b.setAttribute('aria-pressed',b.dataset.v===ABA);b.setAttribute('aria-selected',b.dataset.v===ABA)});
  $('f-cat').innerHTML='<option value="all">Todas</option>'+cats.map(c=>`<option ${c===S.cat?'selected':''}>${esc(c)}</option>`).join('');
  $('f-year').value=S.year;
}
$('f-month').addEventListener('change',e=>{S.month=e.target.value==='all'?'all':+e.target.value;S.day=null;S.limit=15;render()});
// abas: Visão geral (gastos) e Investimentos; lembradas no endereço (#investimentos) e no navegador
let ABA=location.hash==='#investimentos'?'inv':location.hash==='#geral'?'geral':(()=>{try{return localStorage.getItem('lc-aba')||'geral'}catch(e){return 'geral'}})();
function mostrarAba(){
  $('tab-geral').hidden=ABA!=='geral';$('tab-inv').hidden=ABA!=='inv';
  document.querySelectorAll('.so-geral').forEach(el=>el.hidden=ABA!=='geral');
  $('f-tab').querySelectorAll('button').forEach(b=>{b.setAttribute('aria-pressed',b.dataset.v===ABA);b.setAttribute('aria-selected',b.dataset.v===ABA)});
}
$('f-tab').addEventListener('click',e=>{const b=e.target.closest('button');if(!b||b.dataset.v===ABA)return;ABA=b.dataset.v;
  try{localStorage.setItem('lc-aba',ABA)}catch(e){}
  history.replaceState(null,'',ABA==='inv'?'#investimentos':'#geral');
  mostrarAba();drawCharts();scrollTo({top:0})});  // gráficos recriados já visíveis, com a largura certa
mostrarAba();
$('f-cat').addEventListener('change',e=>{S.cat=e.target.value;S.limit=15;render()});
$('f-year').addEventListener('change',e=>{S.year=+e.target.value;S.month='all';S.day=null;S.limit=15;render()});
$('f-q').addEventListener('input',e=>{S.q=e.target.value.trim().toLowerCase();S.limit=15;drawTable()});
$('more').addEventListener('click',()=>{S.limit+=30;drawTable()});

/* ---------- KPIs ---------- */
function delta(cur,prev,upGood,label){
  if(!prev)return '';
  const d=(cur-prev)/prev,good=upGood?d>=0:d<=0;
  return `<span class="delta ${good?'good':'bad'}">${d>=0?'▲':'▼'} ${pct(Math.abs(d))}</span> vs ${label}`;
}
function drawKpis(){
  const s=sums(base()),p=prevPeriod(),ps=p?sums(p.list):null;
  const sobra=s.in-s.out,taxa=s.in?sobra/s.in:0;
  const ano=sums(base({month:'all',cat:'all'}));
  const invA=base({month:'all',cat:'all'}).filter(t=>t.type==='aporte').reduce((x,t)=>(x[isXP(t)?'xp':'inter']+=t.v,x),{inter:0,xp:0});
  $('kpis').innerHTML=`
    <div class="kpi"><span class="eyebrow">Entradas</span><span class="val">${fmt(s.in)}</span><span class="sub">${delta(s.in,ps&&ps.in,true,p&&p.label)||periodLabel()}</span></div>
    <div class="kpi"><span class="eyebrow">Saídas</span><span class="val">${fmt(s.out)}</span><span class="sub">${delta(s.out,ps&&ps.out,false,p&&p.label)||periodLabel()}</span></div>
    <div class="kpi lead"><span class="eyebrow">Sobra do período</span><span class="val">${fmt(sobra)}</span><span class="sub">${s.in?(sobra>=0?'Você guardou '+pct(taxa)+' do que entrou':'Saiu '+pct(-taxa)+' a mais do que entrou'):'Sem entradas no filtro'}</span></div>
    <div class="kpi"><span class="eyebrow">Investido em ${S.year}</span><span class="val">${fmt(ano.inv)}</span><span class="sub">${fmt(invA.inter)} no Inter + ${fmt(invA.xp)} na XP${ano.res?' · resgatou '+fmt(ano.res):''}</span></div>
    <div class="kpi"><span class="eyebrow">Patrimônio investido</span><span class="val">${fmt(invTotal())}</span><span class="sub">${INV?'Inter '+fmt(INV.total):''}${INV&&XP?' + ':''}${XP?'XP '+fmt(XP.patrimonio):''}</span></div>`;
}

/* ---------- gráficos ---------- */
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
function alpha(hex,a){const h=hex.replace('#','');const n=parseInt(h.length===3?h.split('').map(c=>c+c).join(''):h,16);return `rgba(${n>>16&255},${n>>8&255},${n&255},${a})`}
let charts={};
function baseOpts(){
  const line=css('--line');
  Chart.defaults.font.family=css('--f-body');Chart.defaults.color=css('--muted');
  return {responsive:true,maintainAspectRatio:false,animation:{duration:250},
    plugins:{legend:{display:false},tooltip:{backgroundColor:css('--ink'),titleColor:css('--surface'),bodyColor:css('--surface'),padding:10,callbacks:{label:c=>' '+(c.dataset.label?c.dataset.label+': ':'')+fmt(typeof c.parsed==='number'?c.parsed:(c.chart.options.indexAxis==='y'?c.parsed.x:c.parsed.y))}}},
    scales:{x:{grid:{display:false},border:{color:line}},y:{grid:{color:line},border:{display:false},ticks:{callback:v=>fmtK(v)}}}};
}
const pointer=(e,els)=>{e.native.target.style.cursor=els.length?'pointer':'default'};
function drawCharts(){
  Object.values(charts).forEach(c=>c.destroy());charts={};
  const cin=css('--in'),cout=css('--out'),cacc=css('--accent'),cinv=css('--inv'),cwarn=css('--warn'),cmut=css('--muted');
  const ms=monthRange(S.year);
  const data=ms.map(m=>sums(base({month:m})));
  const on=m=>S.month==='all'||S.month===m;
  const o1=baseOpts();
  o1.onClick=(e,els)=>{if(!els.length)return;const m=ms[els[0].index];S.month=S.month===m?'all':m;S.day=null;S.limit=15;render()};
  o1.onHover=pointer;
  charts.m=new Chart($('c-month'),{data:{labels:ms.map(m=>MES[m]),datasets:[
    {type:'line',label:'Sobra',data:data.map(d=>d.in-d.out),borderColor:cacc,backgroundColor:cacc,pointRadius:ms.map(m=>S.month===m?5:2.5),borderWidth:2,tension:.3,order:0},
    {type:'bar',label:'Entradas',data:data.map(d=>d.in),backgroundColor:ms.map(m=>on(m)?cin:alpha(cin,.25)),borderRadius:3,maxBarThickness:22,order:1},
    {type:'bar',label:'Saídas',data:data.map(d=>d.out),backgroundColor:ms.map(m=>on(m)?cout:alpha(cout,.25)),borderRadius:3,maxBarThickness:22,order:1}
  ]},options:o1});
  $('t-month').textContent='Entradas e saídas por mês · '+S.year;
  // categorias
  // "para onde foi" inclui o que foi investido (aportes brutos), além dos gastos
  const byCat={};base({cat:'all'}).filter(t=>t.type==='saida'||t.type==='aporte').forEach(t=>byCat[t.cat]=(byCat[t.cat]||0)+t.v);
  // ordem por valor, com "Outros" sempre por último
  const ce=Object.entries(byCat).sort((a,b)=>(a[0]==='Outros')-(b[0]==='Outros')||b[1]-a[1]);
  const pickCat=c=>{S.cat=S.cat===c?'all':c;S.limit=15;render()};
  $('cat-view').querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',b.dataset.v===CV));
  if(CV==='pie'){drawPie(ce,cmut,pickCat)}else{
  $('cat-legend').hidden=true;
  const o2=baseOpts();o2.indexAxis='y';
  o2.scales={x:{grid:{color:css('--line')},border:{display:false},ticks:{callback:v=>fmtK(v),maxTicksLimit:4,maxRotation:0,autoSkip:true}},y:{grid:{display:false},border:{color:css('--line')},ticks:{color:css('--ink'),autoSkip:false,font:{size:12}}}};
  $('cat-wrap').style.height=Math.max(290,ce.length*24+40)+'px';
  o2.onClick=(e,els)=>{if(els.length)pickCat(ce[els[0].index][0])};
  o2.onHover=pointer;
  const colr=c=>c==='Outros'?cmut:c==='Investimentos'?cinv:cout;
  charts.c=new Chart($('c-cat'),{type:'bar',data:{labels:ce.map(e=>e[0]),datasets:[{data:ce.map(e=>e[1]),backgroundColor:ce.map(e=>S.cat==='all'||S.cat===e[0]?colr(e[0]):alpha(colr(e[0]),.22)),borderRadius:3,maxBarThickness:18}]},options:o2});
  }
  // fluxo mensal para investimentos (lado do Inter)
  const iv=ms.map(m=>{const l=base({month:m,cat:'all'}),s=sums(l),xp=l.filter(t=>isXP(t)&&t.type==='aporte').reduce((a,t)=>a+t.v,0);return {inter:s.inv-xp,xp,res:s.res}});
  const o3=baseOpts();
  o3.scales.x.stacked=true;o3.scales.y.stacked=true;
  charts.f=new Chart($('c-flux'),{type:'bar',data:{labels:ms.map(m=>MES[m]),datasets:[
    {label:'CDB e fundos Inter',data:iv.map(d=>d.inter),backgroundColor:alpha(cinv,.4),maxBarThickness:18},
    {label:'Envios para XP',data:iv.map(d=>d.xp),backgroundColor:alpha(cacc,.55),maxBarThickness:18},
    {label:'Resgates',data:iv.map(d=>-d.res),backgroundColor:alpha(cwarn,.55),maxBarThickness:18}
  ]},options:o3});
  // Inter + XP empilhados por mês
  if(INV||XP){
    const xpM={};if(XP){XP.mensal.forEach(r=>xpM[r.data.slice(0,7)]=r.final);xpM[XP.atualizado_em.slice(0,7)]=XP.patrimonio}
    const inM={};if(INV)INV.mensal.forEach(m=>inM[m.mes]=m.valor);
    const ks=[...new Set([...Object.keys(xpM),...Object.keys(inM)])].sort();
    const o6=baseOpts();o6.scales.x.stacked=true;o6.scales.y.stacked=true;o6.scales.x.ticks={maxRotation:0,autoSkip:true,maxTicksLimit:8};
    o6.plugins.tooltip.mode='index';o6.plugins.tooltip.callbacks.footer=it=>'Total: '+fmt(it.reduce((x,c)=>x+c.parsed.y,0));
    charts.t=new Chart($('c-total'),{type:'bar',data:{labels:ks.map(k=>mesAno(k+'-01')),datasets:[
      {label:'Inter',data:ks.map(k=>inM[k]??0),backgroundColor:alpha(css('--p6'),.75),maxBarThickness:22},
      {label:'XP',data:ks.map(k=>xpM[k]??0),backgroundColor:alpha(cinv,.75),maxBarThickness:22}
    ]},options:o6});
  }
  // XP: patrimônio, aportes e rendimento mês a mês
  if(XP){
    const xm=XP.mensal,o4=baseOpts(),o5=baseOpts();
    o4.scales.y.beginAtZero=true;
    o4.scales.x.ticks={maxRotation:0,autoSkip:true,maxTicksLimit:8};o5.scales.x.ticks={maxRotation:0,autoSkip:true,maxTicksLimit:8};
    charts.i=new Chart($('c-inv'),{data:{labels:xm.map(r=>mesAno(r.data)),datasets:[
      {type:'line',label:'Patrimônio',data:xm.map(r=>r.final),borderColor:cinv,backgroundColor:alpha(cinv,.10),fill:true,tension:.3,pointRadius:2,borderWidth:2,order:0,yAxisID:'y'},
      {type:'bar',label:'Aportes líquidos',data:xm.map(r=>r.aportes_liquidos),backgroundColor:alpha(cacc,.55),maxBarThickness:14,order:1,yAxisID:'y'}
    ]},options:o4});
    o5.plugins.tooltip.callbacks.label=c=>{const r=xm[c.dataIndex];return ` ${sgn(r.rendimento)} · ${pctN(r.rent_pct)} · ${pctN(r.pct_cdi,0)} do CDI`};
    charts.r=new Chart($('c-rend'),{type:'bar',data:{labels:xm.map(r=>mesAno(r.data)),datasets:[{data:xm.map(r=>r.rendimento),backgroundColor:xm.map(r=>r.rendimento>=0?cin:cout),borderRadius:2,maxBarThickness:14}]},options:o5});
    // XP × CDI × IPCA, acumulado mês a mês (IPCA para no último mês divulgado)
    if(IND&&xm.every(r=>r.cdi_pct!=null)){
      const acc=k=>{let f=1,ok=true;return xm.map(r=>{if(r[k]==null)ok=false;if(!ok)return null;f*=1+r[k]/100;return +((f-1)*100).toFixed(2)})};
      const sx=acc('rent_pct'),sc=acc('cdi_pct'),si=acc('ipca_pct'),o7=baseOpts();
      o7.scales.x.ticks={maxRotation:0,autoSkip:true,maxTicksLimit:6};o7.scales.y.ticks={callback:v=>v+'%'};
      o7.plugins.tooltip.mode='index';o7.plugins.tooltip.intersect=false;
      o7.plugins.tooltip.callbacks.label=c=>c.parsed.y==null?null:` ${c.dataset.label}: ${pctN(c.parsed.y)}`;
      const ln=(label,data,color,w)=>({label,data,borderColor:color,backgroundColor:color,borderWidth:w,pointRadius:0,tension:.25,spanGaps:false});
      $('bench-box').hidden=false;  // visível antes de criar o gráfico, senão ele nasce com largura 0
      charts.b=new Chart($('c-bench'),{type:'line',data:{labels:xm.map(r=>mesAno(r.data)),datasets:[
        ln('XP',sx,cinv,2.5),ln('CDI',sc,cacc,1.5),ln('IPCA',si,cwarn,1.5)]},options:o7});
      const iu=si.findLastIndex(v=>v!=null),real=iu<0?null:((1+sx[iu]/100)/(1+si[iu]/100)-1)*100;
      $('bench-note').innerHTML=`Desde a abertura: XP ${pctN(sx.at(-1))}, CDI ${pctN(sc.at(-1))}`+
        (iu<0?'.':`, IPCA ${pctN(si[iu])} até ${mesAno(xm[iu].data)}. Acima da inflação até lá: <b class="${cl(real)}">${pctN(real)}</b>.`)+
        ' CDI e IPCA da API do Banco Central.';
    }
  }
}

/* ---------- pizza ---------- */
let CV='bar';try{CV=localStorage.getItem('lc-catview')||'bar'}catch(e){}
$('cat-view').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;CV=b.dataset.v;try{localStorage.setItem('lc-catview',CV)}catch(e){}drawCharts()});
function drawPie(ce,cmut,pickCat){
  // 8 maiores categorias com cor própria; o resto vira "Demais categorias"; "Outros" em cinza
  const named=ce.filter(e=>e[0]!=='Outros'),top=named.slice(0,8),rest=named.slice(8),outros=ce.find(e=>e[0]==='Outros');
  let pi=0;const sl=top.map(e=>({n:e[0],v:e[1],c:e[0]==='Investimentos'?css('--inv'):css('--p'+(++pi===3?++pi:pi)),click:true}));
  if(rest.length)sl.push({n:'Demais categorias ('+rest.length+')',v:rest.reduce((a,e)=>a+e[1],0),c:css('--p9'),click:false});
  if(outros)sl.push({n:'Outros',v:outros[1],c:cmut,click:true});
  const tot=sl.reduce((a,x)=>a+x.v,0);
  $('cat-wrap').style.height='260px';
  const o=baseOpts();delete o.scales;o.cutout='58%';
  o.plugins.tooltip.callbacks.label=c=>` ${fmt(c.parsed)} · ${pct(c.parsed/tot)}`;
  o.onClick=(e,els)=>{if(els.length&&sl[els[0].index].click)pickCat(sl[els[0].index].n)};
  o.onHover=pointer;
  charts.c=new Chart($('c-cat'),{type:'doughnut',data:{labels:sl.map(x=>x.n),datasets:[{data:sl.map(x=>x.v),backgroundColor:sl.map(x=>S.cat==='all'||S.cat===x.n?x.c:alpha(x.c,.25)),borderColor:css('--surface'),borderWidth:2}]},options:o});
  const lg=$('cat-legend');lg.hidden=false;
  lg.innerHTML=sl.map(x=>`<button type="button" data-c="${esc(x.n)}" ${x.click?'':'disabled'}><i style="background:${x.c}"></i><span class="nm">${esc(x.n)}</span><span class="num">${fmt(x.v)}</span><span class="pc">${pct(x.v/tot)}</span></button>`).join('');
  lg.onclick=e=>{const b=e.target.closest('button');if(b&&!b.disabled)pickCat(b.dataset.c)};
}

/* ---------- insights ---------- */
let IP='filtro';
$('ins-period').innerHTML='<option value="filtro">Mesmo dos filtros</option><option value="vida">Vida toda ('+PRIMEIRO.getFullYear()+'–'+HOJE.getFullYear()+')</option>'+YEARS.map(y=>`<option value="${y}">${y}</option>`).join('');
$('ins-period').addEventListener('change',e=>{IP=e.target.value;drawInsights()});
const dd=d=>d.toLocaleDateString('pt-BR');
const dia0=d=>Date.UTC(d.getFullYear(),d.getMonth(),d.getDate());
const nDias=(a,b)=>Math.round((dia0(b)-dia0(a))/864e5)+1;
function insScope(){
  const f=t=>(S.acc==='all'||t.acc===S.acc)&&(S.cat==='all'||t.cat===S.cat);
  const clamp=(a,b)=>[new Date(Math.max(+PRIMEIRO,+a)),new Date(Math.min(+HOJE,+b))];
  if(IP==='vida')return {list:tx.filter(f),label:'toda a vida da conta',ini:PRIMEIRO,fim:HOJE};
  if(IP!=='filtro'){const y=+IP,[ini,fim]=clamp(new Date(y,0,1),new Date(y,11,31,23));return {list:tx.filter(t=>t.d.getFullYear()===y&&f(t)),label:String(y),ini,fim}}
  const [ini,fim]=S.month==='all'?clamp(new Date(S.year,0,1),new Date(S.year,11,31,23)):clamp(new Date(S.year,S.month,1),new Date(S.year,S.month+1,0,23));
  return {list:base(),label:periodLabel(),ini,fim,yearList:base({month:'all'})};
}
function drawInsights(){
  const sc=insScope(),out=[];
  const list=sc.list.filter(t=>t.type==='saida'),total=list.reduce((a,t)=>a+t.v,0);
  // mês que mais gastou: no ano do filtro, ou dentro do período escolhido
  const byM={};(sc.yearList||sc.list).filter(t=>t.type==='saida').forEach(t=>{const k=t.d.getFullYear()*12+t.d.getMonth();byM[k]=(byM[k]||0)+t.v});
  const ks=Object.keys(byM).map(Number);
  if(ks.length){
    const k=ks.reduce((a,b)=>byM[b]>byM[a]?b:a),lo=Math.min(...ks),hi=Math.max(...ks),avg=Object.values(byM).reduce((a,b)=>a+b,0)/(hi-lo+1);
    out.push(['--out','Mês que mais gastou',`${cap(MES_L[k%12])} de ${Math.floor(k/12)}: ${fmt(byM[k])}`,`${fmt(byM[k]-avg)} acima da média mensal do período (${fmt(avg)})`]);
  }
  if(!list.length){out.push(['--muted','Sem gastos','Nada encontrado','Ajuste os filtros ou o período dos insights.'])}
  else{
    const bc={};list.forEach(t=>bc[t.cat]=(bc[t.cat]||0)+t.v);
    const ident=Object.entries(bc).filter(([c])=>c!=='Outros'&&c!=='Pix para pessoas').sort((a,b)=>b[1]-a[1]);
    if(ident.length){const [cn,cv]=ident[0];out.push(['--warn','Categoria que mais pesou',`${cn}: ${fmt(cv)}`,`${pct(cv/total)} de tudo que saiu (sem contar Outros e Pix para pessoas)`])}
    if(bc.Outros){
      const od={};list.filter(t=>t.cat==='Outros').forEach(t=>od[t.desc]=(od[t.desc]||0)+t.v);
      const [on]=Object.entries(od).sort((a,b)=>b[1]-a[1])[0];
      out.push(['--muted','Sem categoria',`${pct(bc.Outros/total)} dos gastos em "Outros"`,`${list.filter(t=>t.cat==='Outros').length} transações · maior: ${esc(on)}`]);
    }
    const big=list.reduce((a,b)=>b.v>a.v?b:a);
    out.push(['--out','Maior gasto único',fmt(big.v),`${esc(big.desc)} · ${dd(big.d)} · ${big.cat}`]);
  }
  const rec=sc.list.filter(t=>t.type==='entrada'&&t.tit==='Pix recebido');
  if(rec.length){const r=rec.reduce((a,b)=>b.v>a.v?b:a);out.push(['--in','Maior Pix recebido',fmt(r.v),`${esc(r.desc)} · ${dd(r.d)} · ${r.cat}`])}
  if(XP){
    const k0=sc.ini.getFullYear()*12+sc.ini.getMonth(),k1=sc.fim.getFullYear()*12+sc.fim.getMonth();
    const xr=XP.mensal.filter(r=>{const k=+r.data.slice(0,4)*12+(+r.data.slice(5,7)-1);return k>=k0&&k<=k1});
    if(xr.length){const v=xr.reduce((x,r)=>x+r.rendimento,0),b=xr.reduce((x,r)=>r.rent_pct>x.rent_pct?r:x);
      out.push(['--inv','Rendimento na XP',`<span class="${cl(v)}">${sgn(v)}</span>`,`${xr.length} ${xr.length>1?'meses':'mês'} · melhor: ${mesAno(b.data)} (${pctN(b.rent_pct)})`])}
  }
  if(list.length){
    const bd=Array(7).fill(0);list.forEach(t=>bd[t.d.getDay()]+=t.v);
    const di=bd.indexOf(Math.max(...bd));
    out.push(['--accent','Dia da semana mais caro',cap(DOW[di]),`${pct(bd[di]/total)} de tudo que saiu no período`]);
    const dl=list.filter(isDelivery);
    if(dl.length){const s=dl.reduce((a,t)=>a+t.v,0);out.push(['--warn','Delivery',`${dl.length} pedidos · ${fmt(s)}`,`iFood e 99Food · média de ${fmt(s/dl.length)} por pedido`])}
  }
  const days=nDias(sc.ini,sc.fim);
  if(days>0){
    out.push(['--inv','Gasto médio por dia',fmt(total/days),`De ${dd(sc.ini)} a ${dd(sc.fim)} · ${days.toLocaleString('pt-BR')} dias`]);
    // dias sem nenhum dinheiro saindo da conta (gastos e investimentos), e a maior sequência
    const mov=new Set(sc.list.filter(t=>t.type==='saida'||t.type==='aporte').map(t=>t.ds));
    let livres=0,run=0,best=0,bestEnd=null;
    for(let d=new Date(sc.ini.getFullYear(),sc.ini.getMonth(),sc.ini.getDate(),12);d<=sc.fim||dia0(d)===dia0(sc.fim);d.setDate(d.getDate()+1)){
      const k=`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
      if(mov.has(k)){run=0;continue}
      livres++;run++;if(run>best){best=run;bestEnd=new Date(d)}
      if(dia0(d)>=dia0(sc.fim))break;
    }
    const bestIni=bestEnd&&new Date(bestEnd.getFullYear(),bestEnd.getMonth(),bestEnd.getDate()-best+1);
    out.push(['--in','Dias sem gastar',`${livres.toLocaleString('pt-BR')} de ${days.toLocaleString('pt-BR')} dias`,best?`Maior sequência: ${best} ${best>1?'dias seguidos':'dia'}, de ${dd(bestIni)} a ${dd(bestEnd)}`:'Você movimentou dinheiro todos os dias do período']);
  }
  $('insights').innerHTML=out.map(([c,tag,big,sub])=>`<div class="ins"><span class="eyebrow tag"><i style="background:var(${c})"></i>${tag}</span><span class="big">${big}</span><span class="sub">${sub}</span></div>`).join('');
  $('ins-scope').textContent='Calculados para '+sc.label+(S.acc!=='all'?' · '+S.acc:'')+(S.cat!=='all'?' · '+S.cat:'');
}

/* ---------- calendário ---------- */
function drawCal(){
  const m=S.month==='all'?lastMonth(S.year):S.month,y=S.year;
  const first=new Date(y,m,1).getDay(),dim=new Date(y,m+1,0).getDate();
  const bd=Array(dim+1).fill(0);
  base({month:m}).filter(t=>t.type==='saida').forEach(t=>bd[t.d.getDate()]+=t.v);
  const max=Math.max(...bd,1);
  let h=['D','S','T','Q','Q','S','S'].map(d=>`<div class="dow">${d}</div>`).join('');
  for(let i=0;i<first;i++)h+='<div class="day empty"></div>';
  for(let d=1;d<=dim;d++){
    const dt=new Date(y,m,d,12),off=dt>HOJE||dt<new Date(PRIMEIRO.getFullYear(),PRIMEIRO.getMonth(),PRIMEIRO.getDate()),v=bd[d],k=v?Math.max(8,Math.round(v/max*85)):0;
    const bg=k?`background:color-mix(in srgb,var(--out) ${k}%,var(--surface-2));${k>55?'color:var(--surface)':''}`:'';
    h+=`<button type="button" class="day" data-d="${d}" style="${bg}" aria-pressed="${S.day===d&&S.month===m}" ${off?'disabled':''} aria-label="${d} de ${MES_L[m]}: ${fmt(v)}"><span class="n">${d}</span><span class="a">${v?fmtK(v).replace('R$ ',''):''}</span></button>`;
  }
  $('cal').innerHTML=h;
  $('cal-title').textContent='Calendário · '+MES_L[m]+' '+y;
}
$('cal').addEventListener('click',e=>{const b=e.target.closest('.day');if(!b||b.disabled||!b.dataset.d)return;const d=+b.dataset.d;
  if(S.month==='all')S.month=lastMonth(S.year);
  S.day=S.day===d?null:d;S.limit=15;render()});

/* ---------- extrato ---------- */
function drawTable(){
  const list=sel();
  const rows=list.slice(0,S.limit).map(t=>{
    const cls={entrada:'in',saida:'out',aporte:'inv',resgate:'inv',transf:'tr'}[t.type],sign=(t.type==='entrada'||t.type==='resgate'||(t.type==='transf'&&/recebido|devolvido/i.test(t.tit)))?'+':'−';
    return `<tr><td class="num">${t.d.toLocaleDateString('pt-BR',{day:'2-digit',month:'2-digit',year:'2-digit'})}</td><td title="${esc(t.tit)}">${esc(t.desc)}</td><td><span class="pill" title="${esc(t.mot)}">${esc(t.cat)}${t.prod?' · '+(isXP(t)?'XP':'Inter'):''}</span></td><td class="acc">${t.acc}</td><td class="v ${cls}">${sign} ${fmt(t.v)}</td></tr>`}).join('');
  $('tbody').innerHTML=rows||`<tr><td colspan="5" class="empty-msg">Nenhuma transação com esses filtros.</td></tr>`;
  $('more').hidden=list.length<=S.limit;
  const ch=[];
  if(S.month!=='all')ch.push(['month',MES_L[S.month]+' '+S.year]);
  if(S.day)ch.push(['day','dia '+S.day]);
  if(S.acc!=='all')ch.push(['acc',S.acc]);
  if(S.cat!=='all')ch.push(['cat',S.cat]);
  if(S.q)ch.push(['q','"'+S.q+'"']);
  $('chips').innerHTML=ch.map(([k,l])=>`<button type="button" data-k="${k}" aria-label="Remover filtro ${esc(l)}">${esc(l)} ✕</button>`).join('')+`<span style="font-size:.8rem;color:var(--muted);align-self:center">${list.length} transações · passe o mouse na categoria para ver o motivo</span>`;
}
$('chips').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;const k=b.dataset.k;
  if(k==='month'){S.month='all';S.day=null}else if(k==='day')S.day=null;else if(k==='q'){S.q='';$('f-q').value=''}else S[k]='all';render()});

/* ---------- maiores destinos ---------- */
function drawTop(){
  const od={},oc={};base().filter(t=>t.type==='saida').forEach(t=>{od[t.desc]=(od[t.desc]||0)+t.v;oc[t.desc]=t.cat});
  const e=Object.entries(od).sort((a,b)=>b[1]-a[1]).slice(0,8);
  if(!e.length){$('top').innerHTML='<p class="empty-msg">Sem gastos no filtro atual.</p>';return}
  const mx=e[0][1];
  $('top').innerHTML=e.map(([d,v])=>`<button type="button" data-q="${esc(d)}"><span class="nm">${esc(d)} <span style="color:var(--muted);font-size:.78rem">· ${esc(oc[d])}</span></span><span class="num">${fmt(v)}</span><span class="bar"><span class="${oc[d]==='Outros'?'o':''}" style="width:${v/mx*100}%"></span></span></button>`).join('');
}
$('top').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;S.q=b.dataset.q.toLowerCase();$('f-q').value=b.dataset.q;S.limit=15;drawTable();$('f-q').scrollIntoView({behavior:'smooth',block:'center'})});

/* ---------- investimentos ---------- */
function drawInv(){
  drawInter();
  const a=sums(base({month:'all',cat:'all'}));
  const xpEnv=base({month:'all',cat:'all'}).filter(t=>isXP(t)&&t.type==='aporte').reduce((x,t)=>x+t.v,0);
  $('flux-note').textContent=`Em ${S.year}: ${fmt(a.inv)} investidos (${fmt(a.inv-xpEnv)} em CDB e fundos do Inter, ${fmt(xpEnv)} enviados para a XP) e ${fmt(a.res)} resgatados.`;
  $('src-inter').textContent=`${tx.length.toLocaleString('pt-BR')} transações de ${PRIMEIRO.toLocaleDateString('pt-BR')} a ${HOJE.toLocaleDateString('pt-BR')}.`;
  if(!XP){$('xp-sec').hidden=true;return}
  const P=XP.performance,xm=XP.mensal;
  const best=xm.reduce((x,r)=>r.rent_pct>x.rent_pct?r:x),worst=xm.reduce((x,r)=>r.rent_pct<x.rent_pct?r:x);
  const prov=XP.lancamentos_recentes.filter(l=>l.tipo==='provento'),provS=prov.reduce((x,l)=>x+l.valor,0);
  const st=[
    ['Patrimônio hoje',fmt(XP.patrimonio),`${fmt(XP.saldo_conta)} parados em conta`],
    ['Rendimento total',`<span class="${cl(P.desde_inicio.rendimento)}">${sgn(P.desde_inicio.rendimento)}</span>`,`${pctN(P.desde_inicio.rent_pct)} · ${pctN(P.desde_inicio.pct_cdi,0)} do CDI desde ${dmY(XP.abertura)}`],
    ['Últimos 12 meses',`<span class="${cl(P.doze_meses.rendimento)}">${sgn(P.doze_meses.rendimento)}</span>`,`${pctN(P.doze_meses.rent_pct)} · ${pctN(P.doze_meses.pct_cdi,0)} do CDI`],
    ['Você aportou',fmt(P.desde_inicio.aportes_liquidos),'Aportes menos retiradas, desde a abertura'],
    ['Meses no positivo',`${P.meses_positivos} de ${P.meses_positivos+P.meses_negativos}`,`Melhor: ${mesAno(best.data)} (${pctN(best.rent_pct)}) · pior: ${mesAno(worst.data)} (${pctN(worst.rent_pct)})`],
    ['Proventos recebidos',fmt(provS),`${prov.length} pagamentos (JCP e dividendos) desde ${dmY(prov[0]?prov[0].data:XP.atualizado_em)}`]
  ];
  $('xp-stats').innerHTML=st.map(([l,v,s])=>`<div class="st"><span class="eyebrow">${l}</span><b>${v}</b><span>${s}</span></div>`).join('');
  $('xp-ref').textContent=`Posição de ${dmY(XP.atualizado_em)} · conta aberta em ${dmY(XP.abertura)}`;
  $('xp-anos').innerHTML='<thead><tr><th>Ano</th><th class="v">Aportes líq.</th><th class="v">Rendimento</th><th class="v">Rentab.</th><th class="v">% do CDI</th><th class="v">Patrimônio final</th></tr></thead><tbody>'+
    XP.por_ano.map(r=>`<tr><td>${r.ano}</td><td class="v">${fmt(r.aportes_liquidos)}</td><td class="v ${cl(r.rendimento)}">${sgn(r.rendimento)}</td><td class="v ${cl(r.rent_pct)}">${pctN(r.rent_pct)}</td><td class="v">${pctN(r.pct_cdi,0)}</td><td class="v">${fmt(r.final)}</td></tr>`).join('')+'</tbody>';
  const tot=XP.posicoes.reduce((x,p)=>x+p.valor,0),grupos={};
  XP.posicoes.forEach(p=>(grupos[p.classe]??=[]).push(p));
  $('xp-total').textContent=fmt(tot)+' investidos';
  $('xp-pos').innerHTML=Object.entries(grupos).map(([c,ps])=>{const v=ps.reduce((x,p)=>x+p.valor,0);
    return `<div class="xp-cls"><header><span>${c}</span><span class="num">${fmt(v)} · ${pct(v/tot)}</span></header>`+ps.map(p=>{const r=p.aplicado==null?null:p.valor-p.aplicado;
      return `<div class="xp-a"><span class="nm">${esc(p.ativo)}</span><span class="num">${fmt(p.valor)}</span><span class="in2">${esc(p.sub)} · ${esc(p.info)}</span><span class="rs num ${r==null?'':cl(r)}">${r==null?'preço médio não informado':`${sgn(r)} (${pctN(r/p.aplicado*100)})`}</span><span class="bar"><span style="width:${p.valor/tot*100}%"></span></span></div>`}).join('')+'</div>'}).join('');
  $('inv-note').textContent='Os valores da XP vêm do portal deles: patrimônio a mercado, rendimento já descontado de taxas e % do CDI calculado pela XP até 28/10/2026; nos meses seguintes, o % do CDI é calculado aqui com o CDI do Banco Central. Os Pix do Inter para o seu nome só contam como envio para a XP quando aparecem no extrato de lá; os outros ficam como "Entre suas contas".';
  $('src-xp').textContent=`Posição e lançamentos de ${dmY(XP.atualizado_em)} · ${xm.length} meses de evolução · rentabilidade e % do CDI até ${dmY(XP.performance_em||XP.atualizado_em)}.`;
}

/* ---------- Radar B3 ---------- */
// linha da ação e do Ibovespa no mesmo ano, as duas partindo de 100
function spark(s,ib){
  const W=300,H=46,norm=a=>a.map(p=>p[1]/a[0][1]*100),a=norm(s),b=norm(ib),all=[...a,...b],lo=Math.min(...all),hi=Math.max(...all);
  const pts=v=>v.map((y,i)=>`${(i/(v.length-1)*W).toFixed(1)},${(H-2-(y-lo)/(hi-lo||1)*(H-4)).toFixed(1)}`).join(' ');
  const c=a.at(-1)>=100?'var(--in)':'var(--out)';
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true"><polyline points="${pts(b)}" fill="none" stroke="var(--muted)" stroke-width="1" stroke-dasharray="3 3" vector-effect="non-scaling-stroke"/><polyline points="${pts(a)}" fill="none" stroke="${c}" stroke-width="1.8" vector-effect="non-scaling-stroke"/><\/svg>`;  // <\/ evita que o Live Server injete o script dele aqui dentro
}
function drawRadar(){
  if(!RADAR||!RADAR.acoes.length)return;
  $('radar-sec').hidden=false;
  const I=RADAR.ibovespa,pp=v=>v==null?'—':`<span class="${cl(v)}">${v>=0?'+':''}${pctN(v,1)}</span>`,x=(v,d=1)=>v==null?'—':v.toLocaleString('pt-BR',{maximumFractionDigits:d,minimumFractionDigits:d});
  const mine=RADAR.acoes.filter(a=>a.carteira),val=mine.reduce((s,a)=>s+a.carteira.quantidade*a.preco,0),
    apl=mine.reduce((s,a)=>s+(a.carteira.aplicado??0),0),prov=mine.reduce((s,a)=>s+a.carteira.proventos,0);
  $('radar-ref').textContent=`Cotações de ${dmY(I.data)} · não é recomendação de compra ou venda`;
  $('radar-stats').innerHTML=[
    ['Ibovespa',I.pontos.toLocaleString('pt-BR')+' pts',`${pp(I.ret_12m)} em 12 meses · ${pp(I.ret_1m)} no último mês`],
    ['CDI em 12 meses',RADAR.cdi_12m==null?'—':pctN(RADAR.cdi_12m),'O que a renda fixa pós-fixada rendeu no mesmo período'],
    ...(mine.length?[['Suas ações hoje',fmt(val),`${mine.length} ações · ${sgn(val-apl)} sobre o preço médio · ${fmt(prov)} em proventos`]]:[])
  ].map(([l,v,s])=>`<div class="st"><span class="eyebrow">${l}</span><b>${v}</b><span>${s}</span></div>`).join('');
  const ordem=[...RADAR.acoes].sort((a,b)=>(!!b.carteira-!!a.carteira)||a.ticker.localeCompare(b.ticker));
  $('radar').innerHTML=ordem.map(a=>{
    const f=a.fundamentos,banco=f&&f.banco,dist=a.max_52s?(a.preco/a.max_52s-1)*100:null,c=a.carteira;
    const res=c&&c.aplicado!=null?c.quantidade*a.preco-c.aplicado:null;
    const fund=f?[['P/L',x(f.pl)],['P/VP',x(f.pvp,2)],['ROE',f.roe==null?'—':pctN(f.roe,1)],['Margem líquida',banco?'n/a (banco)':f.margem_liquida==null?'—':pctN(f.margem_liquida,1)],
        ['Dív. líquida / patrimônio',banco?'n/a (banco)':f.divida_liq_pl==null?'—':x(f.divida_liq_pl,2)+'x'],['Receita em 5 anos',f.crescimento_receita_5a==null?'—':pp(f.crescimento_receita_5a)]]
      :[['P/L, P/VP, ROE','indisponíveis']];
    return `<article class="rd">
      <div class="rd-top"><div><b>${esc(a.ticker)}</b><small>${esc(a.nome)}${f&&f.subsetor?' · '+esc(f.subsetor):''}</small></div>
        <div class="rd-px">${fmt(a.preco)}<span>${pp(a.ret_12m)} em 12m</span></div></div>
      ${spark(a.serie,I.serie)}
      ${c?`<div class="rd-mine">Na sua carteira: ${c.quantidade} ${c.quantidade==1?'ação':'ações'}${c.aplicado!=null?` · preço médio ${fmt(c.aplicado/c.quantidade)} · <span class="${cl(res)}">${sgn(res)}</span>`:''}${c.proventos?` · ${fmt(c.proventos)} em proventos`:''}</div>`:''}
      <dl>
        ${[['1 mês · 3 meses',`${pp(a.ret_1m)} · ${pp(a.ret_3m)}`],['12m contra o Ibovespa',`${pp(a.ret_12m-I.ret_12m)} p.p.`],
          ['Da máxima do ano',pp(dist)],['Dividend yield 12m',a.dy_12m==null?'—':`<span class="${a.dy_12m>20?'warn':''}">${pctN(a.dy_12m,1)}</span>`],
          ['Volatilidade anual',pctN(a.volatilidade,0)],['Maior queda no ano',`<span class="neg">${pctN(a.maior_queda,0)}</span>`]].map(([k,v])=>`<div><dt>${k}</dt><dd>${v}</dd></div>`).join('')}
        <div class="sep"></div>
        ${fund.map(([k,v])=>`<div><dt>${k}</dt><dd>${v}</dd></div>`).join('')}
      </dl>
      ${a.dy_12m>20?'<small class="warn">Dividend yield muito alto: provável provento extraordinário, que não deve se repetir.</small>':''}
      <div class="rd-acts so-local">
        <button class="btn" type="button" data-acao="analisar" data-t="${esc(a.ticker)}">Analisar</button>
        <button class="btn" type="button" data-acao="ver" data-t="${esc(a.ticker)}" hidden>Último relatório</button>
        ${c?'':`<button class="btn" type="button" data-acao="remover" data-t="${esc(a.ticker)}">Remover</button>`}
      </div>
    </article>`}).join('');
  const semTok=RADAR.acoes.filter(a=>!a.fundamentos).map(a=>a.ticker);
  $('radar-note').innerHTML=`Volatilidade e maior queda medem o quanto a ação oscilou no último ano; P/L e P/VP comparam o preço com o lucro e com o patrimônio da empresa (P/L negativo = prejuízo); ROE é o lucro sobre o patrimônio; dívida líquida negativa = mais caixa que dívida. `+
    `Para acompanhar outra ação: <code>python3 scripts/radar_b3.py --adicionar WEGE3</code>.`+
    (semTok.length?` Sem fundamentos agora: ${semTok.join(', ')}.`:'')+
    ` Fontes: Yahoo Finance (cotações e proventos), Fundamentus (indicadores, último balanço) e brapi.dev (setor e descrição).`;
}

/* ---------- Botões locais (só com scripts/servidor.py rodando) ---------- */
// Markdown dos relatórios → HTML. Escapa tudo antes; só gera as poucas tags abaixo.
function md(txt){
  const inl=s=>esc(s).replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>').replace(/(^|[^*])\*([^*\s][^*]*)\*/g,'$1<i>$2</i>')
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g,'<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  const cells=l=>l.trim().replace(/^\||\|$/g,'').split('|').map(c=>c.trim());
  const L=txt.split('\n'),out=[];let i=0;
  while(i<L.length){
    const l=L[i];
    if(/^\s*\|/.test(l)&&/^\s*\|?[\s:|-]+\|?\s*$/.test(L[i+1]||'')){
      const h=cells(l);i+=2;const rows=[];while(i<L.length&&/^\s*\|/.test(L[i]))rows.push(cells(L[i++]));
      out.push(`<table><thead><tr>${h.map(c=>`<th>${inl(c)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${r.map(c=>`<td>${inl(c)}</td>`).join('')}</tr>`).join('')}</tbody></table>`);continue}
    let m;
    if((m=l.match(/^(#{1,4})\s+(.*)/))){out.push(`<h${m[1].length}>${inl(m[2])}</h${m[1].length}>`);i++;continue}
    if(/^\s*(-{3,}|\*{3,})\s*$/.test(l)){out.push('<hr>');i++;continue}
    if(/^\s*([-*]|\d+\.)\s+/.test(l)){const ol=/^\s*\d+\./.test(l),it=[];
      while(i<L.length&&/^\s*([-*]|\d+\.)\s+/.test(L[i]))it.push(L[i++].replace(/^\s*([-*]|\d+\.)\s+/,''));
      out.push(`<${ol?'ol':'ul'}>${it.map(x=>`<li>${inl(x)}</li>`).join('')}</${ol?'ol':'ul'}>`);continue}
    if(/^>\s?/.test(l)){const q=[];while(i<L.length&&/^>\s?/.test(L[i]))q.push(L[i++].replace(/^>\s?/,''));out.push(`<blockquote>${inl(q.join(' '))}</blockquote>`);continue}
    if(!l.trim()){i++;continue}
    const p=[];while(i<L.length&&L[i].trim()&&!/^(#{1,4}\s|\s*\||\s*([-*]|\d+\.)\s|>)/.test(L[i]))p.push(L[i++]);
    if(!p.length)p.push(L[i++]);
    out.push(`<p>${inl(p.join(' '))}</p>`);
  }
  return out.join('');
}
let ST={tarefas:{},relatorios:[]},pollT=null,vistos=new Set(),API='';  // API: endereço do scripts/servidor.py
async function api(path,body){
  const r=await fetch(API+path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{cache:'no-store'});
  const j=await r.json().catch(()=>({}));
  if(!r.ok&&r.status!==202)throw new Error(j.erro||'Erro '+r.status);
  return j;
}
const rmsg=(t,err)=>{$('radar-msg').textContent=t;$('radar-msg').classList.toggle('err',!!err)};
async function abrirRel(nome){
  try{const r=await api('/api/relatorio?nome='+encodeURIComponent(nome));
    $('rel-title').textContent=nome.replace(/^ANALISE-|\.md$/g,'').replace(/-(\d{4})-(\d\d)-(\d\d)$/,' · $3/$2/$1');
    $('rel-body').innerHTML=md(r.texto);$('rel-dlg').showModal();$('rel-body').scrollTop=0}
  catch(e){rmsg(e.message,true)}
}
function drawLocal(){
  const T=ST.tarefas,rodando=Object.entries(T).filter(([,v])=>v.estado==='rodando').map(([k])=>k);
  document.querySelectorAll('[data-acao="analisar"]').forEach(b=>{const on=T['analise:'+b.dataset.t]?.estado==='rodando';b.disabled=on;b.textContent=on?'Analisando…':'Analisar'});
  document.querySelectorAll('[data-acao="ver"]').forEach(b=>b.hidden=!ST.relatorios.some(r=>r.ticker===b.dataset.t));
  $('sync-btn').disabled=T.sincronizar?.estado==='rodando';$('sync-btn').textContent=$('sync-btn').disabled?'Sincronizando…':'Sincronizar agora';
  $('rel-box').hidden=!ST.relatorios.length;
  $('rel-list').innerHTML=ST.relatorios.map(r=>`<button class="btn" type="button" data-rel="${esc(r.nome)}">${esc(r.ticker)} · ${dmY(r.data)}</button>`).join('');
  const an=rodando.filter(k=>k.startsWith('analise:')).map(k=>k.slice(8));
  if(an.length)rmsg(`Analisando ${an.join(', ')} com o Claude Code… costuma levar de 3 a 8 minutos. Pode continuar usando o painel.`);
}
async function poll(){
  try{
    const ant=ST.tarefas;ST=await api('/api/status');
    for(const[k,v]of Object.entries(ST.tarefas)){
      if(ant[k]?.estado!=='rodando'||v.estado==='rodando'||vistos.has(k+v.fim))continue;
      vistos.add(k+v.fim);
      if(k==='sincronizar'){if(v.estado==='pronto'){location.reload();return}rmsg('A sincronização falhou: '+v.mensagem,true)}
      else if(v.estado==='pronto'){rmsg(`Análise de ${k.slice(8)} pronta.`);abrirRel(v.mensagem)}
      else rmsg(`A análise de ${k.slice(8)} falhou: ${v.mensagem}`,true);
    }
    drawLocal();
  }catch(e){}
  clearTimeout(pollT);
  if(Object.values(ST.tarefas).some(v=>v.estado==='rodando'))pollT=setTimeout(poll,4000);
}
const ORDENS_REV={valor:(a,b)=>b.total-a.total,data:(a,b)=>b.datas[0].localeCompare(a.datas[0])||b.total-a.total,
  qtd:(a,b)=>b.n-a.n||b.total-a.total,sugestao:(a,b)=>(b.confianca||0)-(a.confianca||0)||b.total-a.total};
const escolhasRev={};
function listaRevisar(){
  const opcoes=[...new Set(tx.filter(t=>t.type==='saida'&&t.cat!=='Outros').map(t=>t.cat))].sort();
  // guarda o que já foi escolhido e ainda não foi salvo, para trocar a ordem não apagar
  $('rev').querySelectorAll('select[data-i]').forEach(s=>{escolhasRev[s.dataset.i]=s.value});
  const itens=REVISAR.map((r,i)=>({...r,i})).sort(ORDENS_REV[$('rev-ordem').value]);
  $('rev').innerHTML=itens.map(r=>{const atual=escolhasRev[r.i]??(r.sugestao||'');
    return `<div class="rev-l">
    <div><span class="rev-d">${r.datas.length>3?`${r.datas.length} datas · de ${dmY(r.datas.at(-1))} a ${dmY(r.datas[0])}`:r.datas.map(dmY).join(' · ')}</span>${esc(r.desc)}<small>${r.n}× ${r.sugestao?`· sugestão com ${Math.round(r.confianca*100)}% de confiança`:'· sem sugestão'}</small></div>
    <span class="num">${fmt(r.total)}</span>
    <select data-i="${r.i}" aria-label="Categoria"><option value="">Escolha…</option>${opcoes.map(c=>`<option ${c===atual?'selected':''}>${esc(c)}</option>`).join('')}</select>
    <button class="btn" type="button" data-salvar="${r.i}">Salvar</button></div>`}).join('');
}
function drawRevisar(){
  if(!REVISAR.length)return;
  $('rev-sec').hidden=false;
  try{const o=localStorage.getItem('lc-rev-ordem');if(o&&ORDENS_REV[o])$('rev-ordem').value=o}catch(e){}
  listaRevisar();
  $('rev-ordem').addEventListener('change',e=>{try{localStorage.setItem('lc-rev-ordem',e.target.value)}catch(err){}listaRevisar()});
  $('rev').addEventListener('click',async e=>{const b=e.target.closest('[data-salvar]');if(!b)return;
    const i=+b.dataset.salvar,cat=$('rev').querySelector(`select[data-i="${i}"]`).value;if(!cat)return;
    b.disabled=true;b.textContent='Salvando…';
    try{await api('/api/categoria',{descricao:REVISAR[i].desc,categoria:cat});location.reload()}
    catch(err){b.disabled=false;b.textContent='Salvar';alert(err.message)}});
}
async function initLocal(){
  if(DEMO)return;  // a demonstração pública nunca fala com o servidor do dono
  // servido pelo scripts/servidor.py: API no mesmo endereço. Live Server (ou outra página local): procura o servidor na 8765.
  if(!window.SERVIDOR_LOCAL){
    if(!/^(127\.0\.0\.1|localhost)$/.test(location.hostname))return;  // como arquivo ou no Claude: sem botões
    API='http://127.0.0.1:8765';
  }
  try{ST=await api('/api/status')}
  catch(e){$('radar-dica').hidden=false;return}  // servidor desligado: só a dica de como ligar
  Object.entries(ST.tarefas).forEach(([k,v])=>vistos.add(k+v.fim));
  document.body.classList.add('local');drawLocal();poll();drawRevisar();
  const analisar=async t=>{try{await api('/api/analisar',{ticker:t});rmsg(`Análise de ${t} iniciada.`);poll()}catch(e){rmsg(e.message,true)}};
  $('radar-add').addEventListener('submit',async e=>{e.preventDefault();const t=$('radar-tk').value.trim().toUpperCase();if(!t)return;
    const b=e.submitter||$('radar-add').querySelector('[data-acao="adicionar"]');b.disabled=true;rmsg(`Buscando ${t}…`);
    try{await api('/api/radar/adicionar',{ticker:t});location.reload()}catch(err){rmsg(err.message,true);b.disabled=false}});
  $('radar-add').querySelector('[data-acao="analisar-input"]').addEventListener('click',()=>{const t=$('radar-tk').value.trim().toUpperCase();if(t)analisar(t);else rmsg('Digite o código da ação, como WEGE3.',true)});
  $('radar').addEventListener('click',async e=>{const b=e.target.closest('button[data-acao]');if(!b)return;const t=b.dataset.t;
    if(b.dataset.acao==='analisar')analisar(t);
    if(b.dataset.acao==='ver'){const r=ST.relatorios.find(r=>r.ticker===t);if(r)abrirRel(r.nome)}
    if(b.dataset.acao==='remover'&&confirm(`Parar de acompanhar ${t} no radar?`)){b.disabled=true;try{await api('/api/radar/remover',{ticker:t});location.reload()}catch(err){rmsg(err.message,true);b.disabled=false}}});
  $('rel-list').addEventListener('click',e=>{const b=e.target.closest('[data-rel]');if(b)abrirRel(b.dataset.rel)});
  $('rel-close').addEventListener('click',()=>$('rel-dlg').close());
  $('sync-btn').addEventListener('click',async()=>{try{await api('/api/sincronizar',{});poll()}catch(e){rmsg(e.message,true)}});
}

const invTotal=()=>(INV?INV.total:0)+(XP?XP.patrimonio:0);
const rend12Inter=()=>INV?INV.mensal.slice(-12).reduce((x,m)=>x+(m.rendimento||0),0):0;
function drawInter(){
  const it=tx.filter(t=>t.cat==='Investimentos'&&!isXP(t)),anos={};
  for(const t of it){const y=(anos[t.ds.slice(0,4)]??={ap:0,res:0});if(t.type==='aporte')y.ap+=t.v;else y.res+=t.v}
  $('inter-anos').innerHTML='<thead><tr><th>Ano</th><th class="v">Aplicado</th><th class="v">Resgatado</th><th class="v">Saldo do ano</th></tr></thead><tbody>'+
    Object.entries(anos).sort().map(([y,a])=>`<tr><td>${y}</td><td class="v">${fmt(a.ap)}</td><td class="v">${fmt(a.res)}</td><td class="v">${sgn(a.ap-a.res)}</td></tr>`).join('')+'</tbody>';
  // resumo Inter + XP
  const r12=rend12Inter()+(XP?XP.performance.doze_meses.rendimento:0);
  $('inv-stats').innerHTML=[
    ['Total investido hoje',fmt(invTotal()),'Inter + XP, a valor de mercado'],
    ['No Inter',INV?fmt(INV.total):'—',INV?pct(INV.total/invTotal())+' do total':'Posição não importada'],
    ['Na XP',XP?fmt(XP.patrimonio):'—',XP?pct(XP.patrimonio/invTotal())+' do total':'XP não importada'],
    ['Rendimento em 12 meses',`<span class="${cl(r12)}">${sgn(r12)}</span>`,`Inter ${sgn(rend12Inter())} · XP ${XP?sgn(XP.performance.doze_meses.rendimento):'—'}`],
    ...(IND?[['CDI e IPCA em 12 meses',`${pctN(IND.cdi_12m)} · ${pctN(IND.ipca_12m)}`,`Referência do Banco Central · CDI até ${dmY(IND.cdi_ate)}, IPCA até ${mesAno(IND.ipca_ate+'-01')}`]]:[])
  ].map(([l,v,s])=>`<div class="st"><span class="eyebrow">${l}</span><b>${v}</b><span>${s}</span></div>`).join('');
  $('inv-ref').textContent=INV?`Posição de ${dmY(INV.atualizado_em)}`:'';
  if(!INV){$('inter-stats').innerHTML='';$('inter-pos').innerHTML='<p class="empty-msg">Posição do Inter ainda não importada.</p>';return}
  const P=INV.posicoes,val=P.reduce((x,p)=>x+p.valor,0),apl=P.reduce((x,p)=>x+p.aplicado,0),liq=P.reduce((x,p)=>x+p.liquido,0),imp=P.reduce((x,p)=>x+p.impostos,0),r=val-apl;
  $('inter-stats').innerHTML=[
    ['Valor hoje',fmt(val),`${fmt(liq)} se resgatar tudo hoje`],
    ['Você aplicou',fmt(apl),'Nas aplicações que estão abertas'],
    ['Rendimento atual',`<span class="${cl(r)}">${sgn(r)}</span>`,`${pctN(r/apl*100)} bruto · ${fmt(imp)} de IR/IOF estimado`],
    ['Últimos 12 meses',`<span class="${cl(rend12Inter())}">${sgn(rend12Inter())}</span>`,'Variação do patrimônio menos o que você aplicou']
  ].map(([l,v,s])=>`<div class="st"><span class="eyebrow">${l}</span><b>${v}</b><span>${s}</span></div>`).join('');
  $('inter-ref').textContent=`Posição de ${dmY(INV.atualizado_em)}`;
  $('inter-total').textContent=fmt(val)+' investidos';
  const grupos={};P.forEach(p=>(grupos[p.classe]??=[]).push(p));
  $('inter-pos').innerHTML=Object.entries(grupos).map(([c,ps])=>{const v=ps.reduce((x,p)=>x+p.valor,0);
    return `<div class="xp-cls"><header><span>${c}</span><span class="num">${fmt(v)} · ${pct(v/val)}</span></header>`+ps.map(p=>{const g=p.valor-p.aplicado;
      return `<div class="xp-a"><span class="nm">${esc(p.produto)}</span><span class="num">${fmt(p.valor)}</span><span class="in2">${esc(p.info)} · aplicado ${fmt(p.aplicado)}</span><span class="rs num ${cl(g)}">${sgn(g)} (${pctN(g/p.aplicado*100)})</span><span class="bar"><span style="width:${p.valor/val*100}%;background:var(--p6)"></span></span></div>`}).join('')+'</div>'}).join('');
  $('inter-note').textContent='Posições vindas do Open Finance, que às vezes atualizam o rendimento dos CDBs com atraso. O "aplicado" é o que o próprio Inter considera investido em cada aplicação aberta; resgates antigos já levaram junto o rendimento da época. A tabela por ano vem do extrato da conta.';
}

/* ---------- tema ---------- */
function curTheme(){return document.documentElement.dataset.theme||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light')}
function drawTheme(){$('theme').querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',b.dataset.t===curTheme()))}
try{const t=localStorage.getItem('lc-tema');if(t)document.documentElement.dataset.theme=t}catch(e){}
$('theme').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;
  document.documentElement.dataset.theme=b.dataset.t;try{localStorage.setItem('lc-tema',b.dataset.t)}catch(e){}drawTheme()});
matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>{drawTheme();drawCharts()});
new MutationObserver(drawCharts).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
drawTheme();
if(DEMO){
  $('src-badge').innerHTML='<i style="background:var(--warn)"></i>Demonstração · dados fictícios';
  document.querySelector('header.top .eyebrow').textContent='Projeto pessoal · demonstração';
  document.querySelector('header.top p').innerHTML='Painel de finanças pessoais com extrato, categorias automáticas, insights e investimentos. Esta é uma <b>demonstração com dados fictícios</b>: o painel real roda no computador do dono, com os dados do banco sincronizados por Open Finance. <a href="https://github.com/cauaalmeida01/MeuProjetoFinanceiro">Código no GitHub</a>.';
}
if(SYNC){const d=new Date(SYNC);$('synced').hidden=false;
  $('synced').textContent=`Atualizado a última vez: ${d.toLocaleDateString('pt-BR')} às ${d.toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'})}`}

function render(){drawFilters();drawKpis();drawCharts();drawInsights();drawCal();drawTable();drawTop();drawInv()}
render();
drawRadar();
initLocal();
})();
