// SOFC twin dataset app: a tiny local server (this PC only) for index.html; it runs ../twin_dataset.js.
// Start with dataset_app.bat (one level up). It stops by itself about 40 s after the last app window closes.
// Node.js only, no packages.
const http=require("http"), fs=require("fs"), path=require("path"), {spawn}=require("child_process");
const PORT=8517, ROOT=path.join(__dirname,".."), GEN=path.join(ROOT,"twin_dataset.js");
const FILES=["sofc_twin_dataset.csv.gz","events.csv","summary.json"];
const NAME=/^twin_[A-Za-z0-9_.]+$/;                 // dataset folder names the generator makes; nothing else is served
let job=null, lastPing=Date.now();

function args(q){
  const a=["--days",q.get("days"),"--availability",q.get("availability"),"--part-loads",q.get("pl"),"--hot-standbys",q.get("hs"),
    "--cold-shutdowns",q.get("cs"),"--rated-powers",q.get("rp"),"--rated-hours",q.get("rph"),"--start",q.get("start")];
  return a.some(v=>v==null||v==="")? null: a;
}
function check(a){
  return new Promise(res=>{
    const p=spawn(process.execPath,[GEN,...a,"--check"]); let out="", err="";
    p.stdout.on("data",d=>out+=d); p.stderr.on("data",d=>err+=d);
    p.on("close",code=>res(code===0? {ok:true,plan:JSON.parse(out.trim().replace(/^@plan /,""))}: {ok:false,error:err.trim()||"Check failed."}));
  });
}
function start(a){
  job={running:true,progress:0,error:null,summary:null,started:Date.now()};
  const p=spawn(process.execPath,[GEN,...a]), me=job; let buf="", err="";
  p.stdout.on("data",d=>{ buf+=d; let i; while((i=buf.indexOf("\n"))>=0){ const l=buf.slice(0,i); buf=buf.slice(i+1);
    if(l.startsWith("@progress ")) me.progress=+l.slice(10); else if(l.startsWith("@done ")) me.summary=JSON.parse(l.slice(6)); } });
  p.stderr.on("data",d=>err+=d);
  p.on("close",code=>{ me.running=false; me.progress=code===0?1:me.progress; if(code!==0) me.error=err.trim().split("\n")[0]||"The generator stopped."; });
}
function datasets(){
  return fs.readdirSync(ROOT,{withFileTypes:true}).filter(d=>d.isDirectory()&&NAME.test(d.name)&&fs.existsSync(path.join(ROOT,d.name,"preview.json")))
    .map(d=>{ const f=path.join(ROOT,d.name,"summary.json"); return {name:d.name,made:fs.statSync(f).mtimeMs,summary:JSON.parse(fs.readFileSync(f,"utf8"))}; })
    .sort((a,b)=>b.made-a.made);
}
const send=(res,code,body,type="application/json")=>{ res.writeHead(code,{"Content-Type":type,"Cache-Control":"no-store"}); res.end(typeof body==="string"||Buffer.isBuffer(body)?body:JSON.stringify(body)); };

http.createServer(async(req,res)=>{
  const u=new URL(req.url,"http://localhost"), q=u.searchParams;
  try{
    if(u.pathname==="/") return send(res,200,fs.readFileSync(path.join(__dirname,"index.html")),"text/html; charset=utf-8");
    if(u.pathname==="/api/health") return send(res,200,"sofc-dataset","text/plain");
    if(u.pathname==="/api/ping"){ lastPing=Date.now(); return send(res,200,{ok:true}); }
    if(u.pathname==="/api/check"){ const a=args(q); return send(res,200,a?await check(a):{ok:false,error:"Fill in every field."}); }
    if(u.pathname==="/api/run"&&req.method==="POST"){
      if(job&&job.running) return send(res,409,{error:"A dataset is already being made. Wait for it to finish."});
      const a=args(q), c=a&&await check(a); if(!c||!c.ok) return send(res,400,{error:c?c.error:"Fill in every field."});
      start(a); return send(res,200,{ok:true,plan:c.plan});
    }
    if(u.pathname==="/api/status") return send(res,200,job||{running:false});
    if(u.pathname==="/api/datasets") return send(res,200,datasets());
    const name=q.get("name");
    if(u.pathname==="/api/preview"&&NAME.test(name||"")) return send(res,200,fs.readFileSync(path.join(ROOT,name,"preview.json")));
    if(u.pathname==="/download"&&NAME.test(name||"")&&FILES.includes(q.get("file"))){
      const f=path.join(ROOT,name,q.get("file"));
      res.writeHead(200,{"Content-Type":"application/octet-stream","Content-Length":fs.statSync(f).size,"Content-Disposition":`attachment; filename="${name}_${q.get("file")}"`});
      return fs.createReadStream(f).pipe(res);
    }
    send(res,404,{error:"Not found."});
  }catch(e){ send(res,500,{error:e.message}); }
}).listen(PORT,"127.0.0.1",()=>console.log(`SOFC dataset app on http://127.0.0.1:${PORT}`));

// stop when no app window has pinged for 40 s and nothing is running
setInterval(()=>{ if(Date.now()-lastPing>40000&&!(job&&job.running)) process.exit(0); },5000);
