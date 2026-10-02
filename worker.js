let python;
async function initialize(){
  postMessage({stage:'正在载入浏览器数学环境'});
  importScripts('runtime/pyodide.js');
  python=await loadPyodide({indexURL:new URL('runtime/',self.location.href).href});
  postMessage({stage:'正在初始化 SymPy 符号引擎'});
  await python.loadPackage('sympy');
  const modules=['__init__','syntax','formatting','rules','diagnostics','verification','service'];
  const paths=[...modules.map(name=>`engine/${name}.py`),'data/tests.json','data/robustness.json'];
  const files=await Promise.all(paths.map(async path=>{const response=await fetch(path+'?v=4');if(!response.ok)throw Error('无法读取 '+path);return response.text();}));
  python.FS.mkdirTree('/app/engine');python.FS.mkdirTree('/app/data');
  paths.forEach((path,index)=>python.FS.writeFile('/app/'+path,files[index]));
  const tests=files[modules.length];
  await python.runPythonAsync("import sys,json\nsys.path.insert(0,'/app')\nfrom engine import service");
  postMessage({ready:true,catalog:call({action:'catalog'}),fixtures:JSON.parse(tests)});
}
function call(request){python.globals.set('_request_json',JSON.stringify(request));return JSON.parse(python.runPython("json.dumps(service.dispatch(json.loads(_request_json)),ensure_ascii=False)"));}
onmessage=async({data})=>{
  try{
    if(!python)throw Error('数学引擎仍在载入');
    if(data.request.action==='tests'){
      const fixtures=JSON.parse(python.FS.readFile('/app/data/tests.json',{encoding:'utf8'}));const start=performance.now(),results=[];
      for(const test of fixtures){
        let result;try{result=call({action:'verify',steps:test.steps,context:test.context});}catch(error){result={status:'error',firstError:null,summary:String(error)};}
        const row={...test,actual:result.status,actualFirstError:result.firstError??null,passed:result.status===test.expected&&(result.firstError??null)===test.expectedFirstError,error:result.status==='error'?result.summary:''};
        results.push(row);postMessage({id:data.id,progress:{done:results.length,total:fixtures.length,row}});await new Promise(r=>setTimeout(r,0));
      }
      postMessage({id:data.id,result:{total:results.length,passed:results.filter(x=>x.passed).length,failed:results.filter(x=>!x.passed).length,correctCount:fixtures.filter(x=>x.expected==='correct').length,wrongCount:fixtures.filter(x=>x.expected==='wrong').length,elapsedMs:performance.now()-start,results}});
    }else postMessage({id:data.id,result:call(data.request)});
  }catch(error){postMessage({id:data.id,error:String(error.message||error)});}
};
initialize().catch(error=>postMessage({fatal:String(error.message||error)}));
