"""Run browser logic against minimal fake DOM/fetch implementations in Node."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def node_test(script):
    if not shutil.which("node"):
        pytest.skip("Node.js is required for frontend behavior checks.")
    result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        pytest.fail("Frontend behavior assertion failed: " + result.stderr)


def test_api_transport_attaches_jwt_and_rejects_cross_origin():
    node_test(r"""
const fs = require('fs'); const vm = require('vm'); const assert = require('assert');
const storage = new Map([['accessToken', 'synthetic-token']]);
const calls = [];
const ctx = {window:{}, URL, Headers, localStorage:{getItem:k=>storage.get(k),removeItem:k=>storage.delete(k)},
fetch:async (url, options)=>{calls.push({url,options});return {status:200}}};
vm.createContext(ctx); vm.runInContext(fs.readFileSync('frontend/js/api.js','utf8'),ctx);
(async()=>{
 await ctx.window.apiFetch('/validate_post');
 assert.equal(calls[0].options.headers.get('Authorization'),'Bearer synthetic-token');
 await assert.rejects(()=>ctx.window.apiFetch('https://evil.example/steal'));
 assert.equal(calls.length,1);
 ctx.fetch=async()=>({status:401});
 await assert.rejects(()=>ctx.window.apiFetch('/validate_post'));
 assert.equal(storage.has('accessToken'),false);
})().catch(e=>{console.error(e);process.exitCode=1});
""")


@pytest.mark.parametrize("outcome", ["network", "http_error", "success"])
def test_generation_reports_actual_outcome(outcome):
    node_test(
        r"""
const fs=require('fs'), vm=require('vm'), assert=require('assert');
const alerts=[]; const loading={style:{}};
const element={value:'Synthetic product',addEventListener:()=>{}};
const ctx={document:{querySelector:()=>element,getElementById:()=>loading},alert:m=>alerts.push(m),console:{log:()=>{},error:()=>{}}};
const outcome=OUTCOME;
ctx.apiFetch=async()=>{if(outcome==='network')throw new Error('Network failed');
return outcome==='http_error'?{ok:false,json:async()=>({error:'Generation failed'})}:{ok:true,json:async()=>({result:{slogan:'Synthetic result'}})};};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('frontend/js/runAgents.js','utf8'),ctx);
(async()=>{await ctx.generatePostManually();
assert.equal(alerts.some(x=>x.includes('successfully')),outcome==='success');
assert.equal(loading.style.display,'none');})().catch(e=>{console.error(e);process.exitCode=1});
""".replace("OUTCOME", json.dumps(outcome))
    )


def test_post_content_rendered_as_text_and_images_use_authenticated_loader():
    node_test(r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const nodes=[],images=[];
function node(){const value={children:[],className:'',append(...n){this.children.push(...n)},appendChild(n){this.children.push(n)},addEventListener(){}};nodes.push(value);return value;}
const container=node(); const content='<img src=x onerror=alert(1)>';
const ctx={document:{querySelector:()=>container,createElement:()=>node(),addEventListener(){}},
console:{log(){},error(){}},alert(){throw new Error('Unexpected error')},
loadPrivateImage:(img,path)=>images.push(path),
apiFetch:async()=>({ok:true,json:async()=>[{id:1,post_text:content,image_path:'/images/1'}]})};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('frontend/js/approve_reject.js','utf8'),ctx);
(async()=>{await ctx.fetchDraftPosts();assert(nodes.some(n=>n.textContent===content));
assert(!nodes.some(n=>n.innerHTML&&n.innerHTML.includes(content)));assert.equal(images[0],'/images/1');
})().catch(e=>{console.error(e);process.exitCode=1});
""")


@pytest.mark.parametrize("outcome", ["failure", "duplicate", "network", "success"])
def test_publication_displays_only_confirmed_success(outcome):
    node_test(
        r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const alerts=[];
const ctx={document:{addEventListener(){}},console:{log(){},error(){}},alert:m=>alerts.push(m)};
const outcome=OUTCOME;
ctx.apiFetch=async()=>{
 if(outcome==='network')throw new Error('Connection failed');
 return outcome==='success'?{ok:true,json:async()=>({message:'Post published successfully'})}:
 {ok:false,json:async()=>({error:outcome==='duplicate'?'Already attempted':'Publication failed'})};
};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('frontend/js/approve_reject.js','utf8'),ctx);
ctx.fetchDraftPosts=()=>{};
(async()=>{await ctx.approvePost(1);assert.equal(alerts.length,1);
assert.equal(alerts[0].includes('successfully'),outcome==='success');
})().catch(e=>{console.error(e);process.exitCode=1});
""".replace("OUTCOME", json.dumps(outcome))
    )


def test_chat_history_is_user_scoped_text_and_discards_legacy_html():
    node_test(r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const token='synthetic.'+Buffer.from(JSON.stringify({sub:'1'})).toString('base64url')+'.synthetic';
const storage=new Map([['accessToken',token],['savedchats','<img onerror=unsafe()>'],
['savedchats-v2:1',JSON.stringify([{role:'incoming',text:'<img onerror=unsafe()>'}])],
['savedchats-v2:2',JSON.stringify([{role:'incoming',text:'Other user private message'}])]]);
const placeholder={addEventListener(){}};
const chat={children:[],replaceChildren(){this.children=[]},appendChild(n){this.children.push(n)},scrollTo(){}};
const ctx={atob:s=>Buffer.from(s,'base64').toString(),localStorage:{getItem:k=>storage.get(k),removeItem:k=>storage.delete(k)},
document:{body:{classList:{toggle(){}}},querySelector:q=>q==='.chat-list'?chat:placeholder,querySelectorAll:()=>[],
createElement:()=>{const text={};return {classList:{add(){}},querySelector:()=>text}}}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('frontend/script.js','utf8'),ctx);
assert.equal(storage.has('savedchats'),false);assert.equal(chat.children.length,1);
assert.equal(chat.children[0].querySelector('.text').textContent,'<img onerror=unsafe()>');
assert(!chat.children[0].innerHTML.includes('onerror'));
""")
