"""Synthetic local template contracts; contains no personal or vendor card content."""

import json


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
