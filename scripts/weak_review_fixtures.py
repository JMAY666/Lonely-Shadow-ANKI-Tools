"""Synthetic local template contracts; contains no personal or vendor card content."""

import json


def table_html():
    # Inspected mu-aarea type=2 contract, with synthetic repeated cell answers.
    rows = [[{"text": text, "show": 0} for text in ("", "列一", "列二", "列三")]]
    for index in range(3):
        rows.append(
            [{"text": f"行 {index + 1}", "show": 0}]
            + [
                {"text": text, "show": 0}
                for text in ("相同答案", "相同答案", "<b>格式</b><br>换行")
            ]
        )
    return """<html><style>
body{font:18px sans-serif;margin:8px}table{width:100%;border-collapse:collapse}
th{background:#afd0be}td,th{padding:12px;border:1px solid #ddd;text-align:left}
tr:nth-child(odd){background:#f6f8fa}uni-view{display:block}
</style><body><div cardid="synthetic-table" card="table">
<div class="flex-q-clz">合成表格题目</div><uni-view class="mumu-table" data-v-synthetic></uni-view>
</div><script>
window.testRows=ROWS;
const answerSide=location.search.includes('answer');
window.testComponent={type:{name:'mu-aarea'},props:{flip:answerSide?1:0,card:{answer:{type:2,A:testRows}}},parent:null};
window.renderNative=()=>{
 const host=document.querySelector('.mumu-table:not(.anki-wr-table-host)');
 host.__vueParentComponent={type:{name:'uni-table'},parent:testComponent};
 host.innerHTML='<table class="uni-table table--stripe">'+testRows.map((row,r)=>
  '<tr>'+row.map((cell,c)=>r===0||c===0
   ?'<th class="mumu-table-th"><uni-view><span class="mumu-font-14">'+cell.text+'</span></uni-view></th>'
   :'<td class="mumu-table-td" rowspan="1" colspan="1" data-row="'+r+'" data-col="'+c+'"><span class="mumu-font-14">'+(answerSide||cell.show?cell.text:'(填空)')+'</span></td>'
  ).join('')+'</tr>'+(r===0?'<tr></tr>':'')).join('')+'</table>';
 host.querySelectorAll('td').forEach(td=>td.onclick=()=>{if(!answerSide){const cell=testRows[td.dataset.row][td.dataset.col];cell.show=1-cell.show;renderNative()}});
};
window.rebuildNative=()=>{const host=document.querySelector('.mumu-table:not(.anki-wr-table-host)'),replacement=document.createElement('uni-view');replacement.className='mumu-table';replacement.setAttribute('data-v-synthetic','');host.replaceWith(replacement);renderNative()};
renderNative();
</script></body></html>""".replace("ROWS", json.dumps(rows, ensure_ascii=False))


def studio_html(answer=False):
    body = '<div class="buttons"><button id="showButton" onclick="replaceAndScroll()">N</button><button id="resetButton" onclick="resetButton()">K</button><button id="hideButton" onclick="restoreAndScroll()">J</button></div><div class="answers"><div class="content"><u>保留的划线提示</u><b>普通加粗</b>'
    body += "".join(
        f'<p>合成条目 {i}<span class="aswk">重复答案 {i % 2}</span></p>'
        for i in range(6)
    )
    body += "</div></div>"
    return (
        '<style>.aswk{color:transparent;background:#5c5c50}.aswk.show{color:orange}</style><template id="ak-front">'
        + body
        + """</template><script>
setTimeout(()=>{
 const t=document.getElementById('ak-front');t.replaceWith(t.content.cloneNode(true));
 window.replaceAndScroll=()=>{const e=document.querySelector('.aswk');if(e){const b=document.createElement('b');b.dataset.testBlank='true';b.innerHTML=e.innerHTML;e.replaceWith(b)}};
 window.resetButton=()=>document.querySelectorAll('b[data-test-blank]').forEach(b=>{const s=document.createElement('span');s.className='aswk';s.innerHTML=b.innerHTML;b.replaceWith(s)});
 window.restoreAndScroll=()=>{const a=[...document.querySelectorAll('b[data-test-blank]')];if(a.length){const e=a.pop(),s=document.createElement('span');s.className='aswk';s.innerHTML=e.innerHTML;e.replaceWith(s)}};
 document.querySelector('.answers').addEventListener('click',e=>{const s=e.target.closest('.aswk');if(s)s.classList.toggle('show')});
 if(ANSWER)document.querySelectorAll('.aswk').forEach(e=>e.classList.add('show'));
},80);
</script>""".replace("ANSWER", json.dumps(answer))
    )


def enhanced_html(answer=False):
    content = "".join(
        f"<p>当前条目 {i} {{{{c1::相同答案 {i % 2}}}}}</p>" for i in range(7)
    )
    content += "<p>上下文 {{c2::其他编号 A}}、{{c2::其他编号 B}}</p>"
    return (
        '<style>.genuine-cloze[show-state=hint]{background:pink}.pseudo-cloze{color:#89baff}</style><span id="enhanced-cloze-content" hidden>'
        + content
        + r"""</span><div id="enhanced-clozes"></div>
<div hidden><span class="cloze" data-cloze="hidden helper" data-ordinal="1">[...]</span></div>
<button id="show-one-cloze-right" onclick="showTestCloze()">逐个显示</button>
<script>setTimeout(()=>{
 const content=document.getElementById('enhanced-cloze-content').innerHTML;
 const parts=[...content.matchAll(/\{\{c(\d+)::([\s\S]*?)\}\}/g)];
 window.enhancedClozesData={clozeId:parts.map(x=>x[1]),answers:parts.map(x=>x[2]),hints:parts.map(x=>'')};
 window.toggleCloze=function(el,side){const shown=side==='answer'||(side==='toggle'&&el.getAttribute('show-state')!=='answer');el.setAttribute('show-state',shown?'answer':'hint');el.innerHTML=shown?enhancedClozesData.answers[Number(el.getAttribute('index'))]:'[ ]'};
 window.rebuildTestClozes=()=>{
   let index=0;document.getElementById('enhanced-clozes').innerHTML=content.replace(/\{\{c(\d+)::([\s\S]*?)\}\}/g,(_,cid)=>'<span class="'+(cid==='1'?'genuine':'pseudo')+'-cloze" index="'+(index++)+'" cid="'+cid+'"></span>');
   document.querySelectorAll('.genuine-cloze,.pseudo-cloze').forEach(el=>toggleCloze(el,ANSWER||el.classList.contains('pseudo-cloze')?'answer':'hint'));
 };
 window.showTestCloze=()=>{const e=document.querySelector('.genuine-cloze[show-state=hint]');if(e)toggleCloze(e,'answer')};
 rebuildTestClozes();
 document.getElementById('enhanced-clozes').addEventListener('click',e=>{const el=e.target.closest('.genuine-cloze,.pseudo-cloze');if(el)toggleCloze(el,'toggle')});
},80);</script>""".replace("ANSWER", json.dumps(answer))
    )
