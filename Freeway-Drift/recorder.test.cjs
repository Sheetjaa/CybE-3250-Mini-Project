const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');

function setup(){
 let now=0,captureError=false,encodeError=false,finish;
 const events={},elements=new Map();
 const drawing=new Proxy({}, {get:(target,key)=>target[key]||(()=>{}),set:(target,key,value)=>(target[key]=value,true)});
 class Element {
  constructor(){this.style={};this.dataset={};this.value='0.2';this.classList={toggle(){},add(){},remove(){}};this.handlers={};this.width=640;this.height=480}
  addEventListener(type,fn){this.handlers[type]=fn}
  setAttribute(){} focus(){} click(){} remove(){} append(){} setPointerCapture(){}
  querySelector(){return new Element()}
  getContext(){if(captureError)throw Error('capture failed');return drawing}
  toBlob(callback){if(encodeError){callback(null);return}finish=()=>callback(new Blob(['test pixels']))}
 }
 const element=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id)};
 const context=vm.createContext({Blob,TextEncoder,Uint8Array,DataView,console,Date,Map,Set,HTMLInputElement:class{},HTMLTextAreaElement:class{},performance:{now:()=>now},innerWidth:640,innerHeight:480,devicePixelRatio:1,
  document:{getElementById:element,createElement:()=>new Element(),querySelectorAll:()=>[],addEventListener:(type,fn)=>events[type]=fn,body:new Element(),hidden:false},
  addEventListener:(type,fn)=>events[type]=fn,requestAnimationFrame(){},setTimeout(){},clearTimeout(){},URL:{createObjectURL:()=>'',revokeObjectURL(){}}});
 context.window=context;
 vm.runInContext(fs.readFileSync(path.join(__dirname,'recorder.js'),'utf8'),context);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'game.js'),'utf8'),context);
 const run=code=>vm.runInContext(code,context);
 run('setRunning(true);recorder.start()');
 return {run,events,element,time:value=>now=value,captureError:()=>captureError=true,encodeError:()=>encodeError=true,finish:async()=>{finish();await run('recorder.pending')},flush:async()=>{for(let i=0;i<10;i++)await Promise.resolve()}};
}

test('input changes are immediate, repeats suppressed, overlapping sources stay held',()=>{
 const h=setup();h.time(20);h.run("setKey('w',true,'keyboard','KeyW');setKey('w',true,'keyboard','KeyW');setKey('w',true,'pointer:1')");
 h.time(80);h.run("setKey('w',false,'keyboard','KeyW')");assert.equal(h.run('keys.w'),true);
 h.time(90);h.run("setKey('w',false,'pointer:1')");assert.equal(h.run('keys.w'),false);
 assert.equal(h.run('recorder.events.filter(e=>e.type===\'keydown\').length'),2);
 assert.equal(h.run('recorder.events[1].elapsed_ms'),20);
 assert.equal(h.run('recorder.events[1].epoch_ms-recorder.epoch'),20);
});

test('frame metadata is captured before async encoding; pending capture completes on stop',async()=>{
 const h=setup();h.run("setKey('w',true,'keyboard','KeyW');recorder.tick();car.x=500;setKey('w',false,'keyboard','KeyW')");
 const stopped=h.run("recorder.stop('manual')");await h.finish();await stopped;
 assert.equal(h.run('recorder.frames[0].car.x'),0);
 assert.equal(h.run('recorder.frames[0].keys_held[0]'),'w');
 assert.equal(h.run('recorder.frames[0].actions.accelerate'),true);
 assert.equal(h.run('recorder.archive.type'),'application/zip');
 assert.equal(h.run('recorder.saving'),false);
});

test('pause releases inputs and records stop; reset marks a new segment',async()=>{
 const h=setup();h.run("setKey('a',true,'keyboard','KeyA');reset();setKey('w',true,'keyboard','KeyW');setRunning(false,'blur')");await h.flush();
 assert.equal(h.run('recorder.active'),false);
 assert.equal(h.run('recorder.events.find(e=>e.type===\'reset\').segment'),1);
 assert.equal(h.run('recorder.events.at(-2).reason'),'blur');
 assert.equal(h.run('recorder.events.at(-2).synthetic'),true);
 assert.equal(h.run('recorder.events.at(-1).type'),'stop');
 assert.equal(h.run('recorder.events.at(-1).state.keys_held.length'),0);
});

test('capture failures end recording without throwing out of the game loop',async()=>{
 const h=setup();h.captureError();assert.doesNotThrow(()=>h.run('recorder.tick()'));await h.flush();
 assert.equal(h.run('recorder.active'),false);assert.equal(h.run('recorder.reason'),'capture_error');
 assert.equal(h.run('recorder.error'),'capture failed');
});

test('encoding failure exports diagnostics; skipped cadence slots are counted',async()=>{
 const h=setup();h.time(2500);h.encodeError();h.run('recorder.tick()');await h.flush();
 assert.equal(h.run('recorder.dropped'),12);
 assert.equal(h.run('recorder.reason'),'capture_error');
 assert.equal(h.run('recorder.error'),'PNG encoding failed');
});

test('failed ZIP export keeps images and can be retried without duplicate entries',async()=>{
 const h=setup();h.run('recorder.tick()');await h.finish();
 h.run('originalZip=recordingZip;recordingZip=()=>{throw Error("test export failure")}');
 await h.run("recorder.stop('manual')");assert.equal(h.run('recorder.saveFailed'),true);assert.equal(h.run('recorder.files.length'),1);
 h.run('recordingZip=originalZip');await h.run('recorder.export()');
 assert.equal(h.run('recorder.saveFailed'),false);assert.equal(h.run('recorder.files.length'),0);assert.ok(h.run('recorder.archive.size')>0);
});

test('recording saves its ZIP into the selected recordings folder',async()=>{
 const h=setup();
 h.run(`window.showDirectoryPicker=async()=>({
  name:'recordings',
  getFileHandle:async filename=>{
   window.savedFilename=filename;
   return {createWritable:async()=>({
    write:async archive=>{window.savedArchiveSize=archive.size},
    close:async()=>{},
    abort:async()=>{}
   })}
  }
 })`);
 await h.run('recorder.begin()');
 h.run('recorder.tick()');await h.finish();
 await h.run("recorder.stop('manual')");
 assert.equal(h.run('savedFilename'),`drive-${h.run('recorder.epoch')}.zip`);
 assert.ok(h.run('savedArchiveSize')>0);
 assert.match(h.run("document.getElementById('record-status').textContent"),/Saved .* to recordings/);
 assert.equal(h.run('recorder.saveFailed'),false);
});

test('200 ms cadence captures 600 frames and stops at two minutes',async()=>{
 const h=setup();assert.equal(h.run('recorder.interval'),200);
 for(let t=0;t<120000;t+=200){h.time(t);h.run('recorder.tick()');await h.finish()}
 h.time(120000);h.run('recorder.tick()');await h.flush();
 assert.equal(h.run('recorder.frames.length'),600);
 assert.equal(h.run('recorder.frames.at(-1).elapsed_ms'),119800);
 assert.equal(h.run('recorder.events.at(-1).elapsed_ms'),120000);
 assert.equal(h.run('recorder.reason'),'duration_limit');assert.equal(h.run('recorder.active'),false);
 assert.equal(h.run('recorder.dropped'),0);assert.ok(h.run('recorder.archive.size')>0);
 h.time(121000);h.run('recorder.tick()');assert.equal(h.run('recorder.frames.length'),600);
});

test('capture fits 960 by 540 preserving aspect ratio and never upscales',async()=>{
 const h=setup();
 h.run('canvas.width=2560;canvas.height=1440;recorder.tick()');await h.finish();
 assert.equal(h.run('recorder.frames[0].width'),960);assert.equal(h.run('recorder.frames[0].height'),540);
 assert.equal(h.run('recorder.frames[0].source_width'),2560);
 h.time(200);h.run('canvas.width=1000;canvas.height=2000;recorder.tick()');await h.finish();
 assert.equal(h.run('recorder.frames[1].width'),270);assert.equal(h.run('recorder.frames[1].height'),540);
 h.time(400);h.run('canvas.width=320;canvas.height=180;recorder.tick()');await h.finish();
 assert.equal(h.run('recorder.frames[2].width'),320);assert.equal(h.run('recorder.frames[2].height'),180);
});
