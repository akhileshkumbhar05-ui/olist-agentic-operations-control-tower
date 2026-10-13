"""Browser-independent regressions for Semantic Mesh null handling and node actions."""
from pathlib import Path
import json
import shutil
import subprocess

import pytest


HTML = (Path(__file__).resolve().parents[1] / "app/static/nexus.html").read_text()


def js_function_block(start, end):
    a = HTML.index(start)
    b = HTML.index(end, a)
    return HTML[a:b]


def run_node(source):
    if not shutil.which("node"):
        pytest.skip("Node.js unavailable in test runner")
    result = subprocess.run(
        ["node", "-e", source], capture_output=True, text=True, timeout=12
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    return result.stdout


def test_semantic_denominator_is_null_safe_during_initial_load_and_metric_switch():
    fn = js_function_block("function semanticStageMetric(){", "function semanticSelect(id){")
    assert "const verifiedDenominator=semanticVerification?.denominator;" in fn
    assert "semanticVerification===null?'Awaiting SQL verification':" in fn
    assert "semanticVerification?.denominator!==null" not in fn
    js = f"""
const vm=require('node:vm'),assert=require('node:assert/strict');
const fn={json.dumps(fn)};
function simulate(evidence){{
  const vals={{}},elements={{}};
  const ctx={{
    semanticVerification:evidence,
    semanticMetric:()=>({{
      metric_id:'late_rate',metric_name:'Late Delivery Rate',
      unit:'%',business_definition:'Eligible late deliveries',
      known_caveat:'historical snapshot',exclusions:'not eligible'
    }}),
    semanticPretty:(val,unit)=>String(val)+' '+unit,
    document:{{createElement:()=>({{append(){{}},className:'',textContent:''}})}},
    $:id=>elements[id]??=( {{style:{{}},replaceChildren(){{}}}} ),
    put:(id,value)=>{{vals[id]=value;}}
  }};
  vm.runInNewContext(fn+'\\nsemanticStageMetric();',ctx);
  return vals;
}}
const loading=simulate(null);
assert.equal(loading.bar2Value,'Awaiting SQL verification');
assert.equal(loading.deltaValue,'—');
assert.equal(loading.rightBadge,'DEFINITION ONLY');
const verified=simulate({{verified_value:'6.7731',numerator:'6534',
 denominator:'96470',numerator_label:'Eligible late',
 denominator_label:'All eligible'}});
assert.equal(verified.bar2Value,'96470 number');
assert.equal(verified.deltaValue,'6.7731 %');
assert.equal(verified.rightBadge,'SQL VERIFIED');
const noDenom=simulate({{verified_value:'13220248.9300',
 numerator:'13220248.9300',denominator:null}});
assert.equal(noDenom.bar2Value,'Not applicable');
console.log('pass');
"""
    assert run_node(js).strip() == "pass"


def test_each_semantic_mesh_node_has_distinct_functional_destination():
    functions = js_function_block(
        "function semanticMarkFocusedNode(){",
        "async function verifySemanticMetric(){",
    )
    js = f"""
const vm=require('node:vm'),assert=require('node:assert/strict');
const code={json.dumps(functions)};
const trace=[],nodes=Array.from({{length:5}},(_,i)=>({{
 dataset:{{semanticNode:String(i)}},
 setAttribute:(name,val)=>trace.push('aria:'+i+':'+val)
}}));
const targets=Object.fromEntries(
 ['semanticFocus','semanticDefinition','semanticVerification','semanticEdges']
 .map(id=>[id,{{scrollIntoView:()=>trace.push('scroll:'+id)}}])
);

targets.question={{value:''}};
const ctx={{
 current:'semantics',
 semanticNodeFocused:null,
 semanticVerification:{{published_run:'published-run-1'}},
 semanticMetric:()=>({{
  metric_id:'gmv',metric_name:'Delivered Item GMV',
  business_definition:'Delivered item prices excluding freight',
  exclusions:'Freight'
 }}),
 document:{{querySelectorAll:()=>nodes}},
 $:id=>targets[id],
 put:(id,v)=>{{if(id==='semanticFocus')trace.push('explain:'+v);}},
 verifySemanticMetric:()=>{{trace.push('verify-sql');}},
 openDrawer:()=>{{trace.push('open-investigator');}},
 domainInvestigationPrompt:'',domainRulePrompt:'',domainPromptDomain:null,
}};
vm.runInNewContext(code,ctx);
const events=()=>trace.filter(x=>!x.startsWith('aria:')&&!x.startsWith('explain:'));
vm.runInNewContext('semanticFocusNode(0)',ctx);
assert.deepEqual(events(),['scroll:semanticFocus']);
trace.length=0;
vm.runInNewContext('semanticFocusNode(1)',ctx);
assert.deepEqual(events(),['scroll:semanticDefinition']);
trace.length=0;
vm.runInNewContext('semanticFocusNode(2)',ctx);
assert.deepEqual(events(),['verify-sql','scroll:semanticVerification']);
trace.length=0;
vm.runInNewContext('semanticFocusNode(3)',ctx);
assert.deepEqual(events(),['scroll:semanticEdges']);
trace.length=0;
vm.runInNewContext('semanticFocusNode(4)',ctx);
assert.deepEqual(events(),['open-investigator']);
assert.match(targets.question.value,/metric gmv \\(Delivered Item GMV\\)/);
assert.match(targets.question.value,/Do not invent a verified value/);
trace.length=0;
ctx.current='quality';
vm.runInNewContext('semanticFocusNode(2)',ctx);
assert.deepEqual(events(),[]);
console.log('pass');
"""
    assert run_node(js).strip() == "pass"


def test_action_buttons_and_canvas_share_handler_and_have_no_fake_runtime_lineage():
    for i in range(5):
        assert f'data-semantic-node="{i}"' in HTML
    assert "button.addEventListener('click',()=>semanticFocusNode(Number(button.dataset.semanticNode)))" in HTML
    assert "semanticFocusNode(node.index)" in HTML
    assert "button.setAttribute('aria-pressed'" in HTML
    assert "button.disabled=false" in HTML
    assert "button.disabled=true" in HTML
    assert "if(semanticNodeFocused===i)ellipse" in HTML
    assert "function semanticAskCurrentDefinition()" in HTML
    assert "$('semanticAsk').addEventListener('click',semanticAskCurrentDefinition)" in HTML
    assert "not automatically captured Databricks execution lineage" in HTML
    assert "id=\"semanticDependencies\"" in HTML
    assert "$('semanticWorkspace').scrollIntoView" not in js_function_block(
        "function semanticFocusNode(index){", "async function verifySemanticMetric(){"
    )
    assert "if(index===2)" in HTML
    assert "void verifySemanticMetric();" in HTML
    assert "semanticScrollTo('semanticVerification')" in HTML


def test_original_quality_dashboard_and_metric_query_untouched_by_mesh():
    assert '<iframe id="nativeDashboard"' in HTML
    assert 'id="qualityWorkspace"' in HTML
    assert 'id="domainInspector"' in HTML
    assert "fetch('/api/nexus/quality-gate'" in HTML
    assert "fetch('/api/nexus/semantic-contracts'" in HTML
    assert "'/verify'" in HTML


def test_inline_nexus_script_parses(tmp_path):
    if not shutil.which("node"):
        pytest.skip("Node.js unavailable")
    source = HTML.rsplit("<script>", 1)[1].split("</script>", 1)[0]
    path = tmp_path / "semantic-mesh.js"
    path.write_text(source, encoding="utf-8")
    parsed = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
    assert parsed.returncode == 0, parsed.stderr
