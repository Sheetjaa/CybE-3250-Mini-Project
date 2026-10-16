'use strict';
const RECORDING_MAX_DURATION_MS=120000,RECORDING_MAX_WIDTH=960,RECORDING_MAX_HEIGHT=540;
// Dependency-free, uncompressed ZIP writer. PNG files are already compressed.
function recordingZip(files) {
 const chunks=[], directory=[]; let offset=0;
 const enc=new TextEncoder();
 const table=Array.from({length:256},(_,n)=>{for(let i=0;i<8;i++)n=(n>>>1)^((n&1)?0xedb88320:0);return n>>>0});
 for(const [path,data] of files){
  const name=enc.encode(path);let crc=0xffffffff;for(const b of data)crc=(crc>>>8)^table[(crc^b)&255];crc=(crc^0xffffffff)>>>0;
  const header=new Uint8Array(30+name.length),h=new DataView(header.buffer);
  h.setUint32(0,0x04034b50,true);h.setUint16(4,20,true);h.setUint16(12,33,true);h.setUint32(14,crc,true);h.setUint32(18,data.length,true);h.setUint32(22,data.length,true);h.setUint16(26,name.length,true);header.set(name,30);
  const entry=new Uint8Array(46+name.length),d=new DataView(entry.buffer);
  d.setUint32(0,0x02014b50,true);d.setUint16(4,20,true);d.setUint16(6,20,true);d.setUint16(14,33,true);d.setUint32(16,crc,true);d.setUint32(20,data.length,true);d.setUint32(24,data.length,true);d.setUint16(28,name.length,true);d.setUint32(42,offset,true);entry.set(name,46);
  chunks.push(header,data);directory.push(entry);offset+=header.length+data.length;
 }
 const size=directory.reduce((n,d)=>n+d.length,0),end=new Uint8Array(22),e=new DataView(end.buffer);
 e.setUint32(0,0x06054b50,true);e.setUint16(8,files.length,true);e.setUint16(10,files.length,true);e.setUint32(12,size,true);e.setUint32(16,offset,true);
 return new Blob([...chunks,...directory,end],{type:'application/zip'});
}

class DrivingRecorder {
 constructor(canvas,getState){
  this.canvas=canvas;this.getState=getState;this.active=false;this.saving=false;this.pending=null;
  this.directoryHandle=null;
  this.button=document.getElementById('record');this.status=document.getElementById('record-status');this.intervalInput=document.getElementById('record-interval');
  this.button.addEventListener('click',()=>{if(this.active)this.stop('manual');else if(this.saveFailed){if(this.archive)this.saveExisting();else this.export()}else this.begin()});
  document.getElementById('record-download').addEventListener('click',()=>this.saveExisting());
  addEventListener('beforeunload',e=>{if(this.active||this.saving||this.files?.length){e.preventDefault();e.returnValue=''}});
 }
 stamp(){const elapsed=performance.now()-this.origin;return {epoch_ms:this.epoch+elapsed,elapsed_ms:elapsed}}
 event(type,detail={}){if(this.active)this.events.push({...this.stamp(),type,...detail})}
 async begin(){
  if(this.saving)return;
  if(!this.getState().running){this.status.textContent='Start driving before recording.';return}
  const seconds=Number(this.intervalInput.value);
  if(!Number.isFinite(seconds)||seconds<0.1||seconds>10){this.status.textContent='Choose an interval from 0.1 to 10 seconds.';return}
  if(!this.directoryHandle&&typeof window.showDirectoryPicker==='function'){
   this.status.textContent='Choose the recordings folder to save this session…';
   try{this.directoryHandle=await window.showDirectoryPicker({mode:'readwrite'})}
   catch(error){
    this.status.textContent=error.name==='AbortError'?'Folder selection cancelled. Click Record drive to try again.':`Could not open the recordings folder: ${error.message}`;
    return
   }
  }
  this.start();
 }
 start(){
  if(this.saving||this.saveFailed)return;
  if(!this.getState().running){this.status.textContent='Start driving before recording.';return}
  const seconds=Number(this.intervalInput.value);
  if(!Number.isFinite(seconds)||seconds<0.1||seconds>10){this.status.textContent='Choose an interval from 0.1 to 10 seconds.';return}
  this.origin=performance.now();this.epoch=Date.now();this.interval=seconds*1000;this.next=0;this.events=[];this.frames=[];this.files=[];this.archive=null;this.bytes=0;this.dropped=0;this.error=null;this.initial=this.getState();this.active=true;
  this.event('start',{state:this.initial});
  this.button.textContent='Stop & save';this.intervalInput.disabled=true;
  document.getElementById('record-download').hidden=true;this.status.textContent='Recording: 0 / 120 seconds…';
 }
 tick(){
  if(!this.active)return;
  const stamp=this.stamp();
  if(stamp.elapsed_ms>=RECORDING_MAX_DURATION_MS){this.stop('duration_limit');return}
  if(stamp.elapsed_ms<this.next)return;
  const due=Math.floor((stamp.elapsed_ms-this.next)/this.interval)+1;
  this.next+=due*this.interval;this.dropped+=due-1;
  if(this.pending){this.dropped++;return}
  try{
  const state=this.getState(),path=`frames/${String(this.frames.length).padStart(6,'0')}.png`;
  // Copy synchronously so pixels, state and timestamps describe this rendered frame.
  const sourceWidth=this.canvas.width,sourceHeight=this.canvas.height;
  const scale=Math.min(1,RECORDING_MAX_WIDTH/sourceWidth,RECORDING_MAX_HEIGHT/sourceHeight);
  const copy=document.createElement('canvas');copy.width=Math.max(1,Math.round(sourceWidth*scale));copy.height=Math.max(1,Math.round(sourceHeight*scale));
  const copyContext=copy.getContext('2d');copyContext.imageSmoothingEnabled=true;copyContext.imageSmoothingQuality='high';copyContext.drawImage(this.canvas,0,0,copy.width,copy.height);
  this.pending=new Promise(resolve=>copy.toBlob(resolve,'image/png')).then(async blob=>{
   if(!blob)throw new Error('PNG encoding failed');
   const data=new Uint8Array(await blob.arrayBuffer());this.files.push([path,data]);this.bytes+=data.length;
   this.frames.push({frame:this.frames.length,image:path,...stamp,width:copy.width,height:copy.height,source_width:sourceWidth,source_height:sourceHeight,...state});
   if(this.active)this.status.textContent=`Recording: ${Math.floor(stamp.elapsed_ms/1000)} / 120 seconds · ${this.frames.length} frames · ${(this.bytes/1048576).toFixed(1)} MiB`;
  }).catch(error=>{this.error=error.message}).finally(()=>{
   this.pending=null;
   if(this.active&&(this.bytes>=200*1048576||this.error))this.stop(this.error?'capture_error':'memory_limit');
  });
  }catch(error){this.error=error.message;this.stop('capture_error')}
 }
 async stop(reason){
  if(!this.active)return;
  this.event('stop',{reason,state:this.getState()});this.reason=reason;this.active=false;this.saving=true;this.button.disabled=true;this.status.textContent='Preparing recording…';
  await this.pending;
  await this.export();
 }
 async export(){
  this.saving=true;this.button.disabled=true;this.status.textContent='Preparing download…';
  try{
   const encode=value=>new TextEncoder().encode(value);
   const metadata={schema_version:1,started_epoch_ms:this.epoch,interval_ms:this.interval,max_duration_ms:RECORDING_MAX_DURATION_MS,image_max_width:RECORDING_MAX_WIDTH,image_max_height:RECORDING_MAX_HEIGHT,clock:'epoch_ms = session Date.now() + monotonic elapsed_ms',image_source:'world canvas only; excludes HTML HUD and minimap; scaled to fit image bounds without upscaling',initial_state:this.initial,frame_count:this.frames.length,skipped_captures:this.dropped,stop_reason:this.reason,error:this.error};
   const jsonl=rows=>encode(rows.map(row=>JSON.stringify(row)+'\n').join(''));
   this.archive=recordingZip([...this.files,['session.json',encode(JSON.stringify(metadata,null,2))],['inputs.jsonl',jsonl(this.events)],['frames.jsonl',jsonl(this.frames)]]);
   this.files=[];this.saveFailed=false;document.getElementById('record-download').hidden=false;
   await this.persistArchive();
  }catch(error){this.saveFailed=true;this.status.textContent=`Save failed: ${error.message}. Keep this page open and retry.`}
  finally{this.saving=false;this.button.disabled=false;this.button.textContent=this.saveFailed?'Retry save':'Record drive';this.intervalInput.disabled=!!this.saveFailed}
 }
 async saveExisting(){
  if(!this.archive||this.saving)return;
  this.saving=true;this.button.disabled=true;this.status.textContent='Saving recording…';
  try{await this.persistArchive()}
  catch(error){this.saveFailed=true;this.status.textContent=`Save failed: ${error.message}. Keep this page open and retry.`}
  finally{this.saving=false;this.button.disabled=false;this.button.textContent=this.saveFailed?'Retry save':'Record drive';this.intervalInput.disabled=!!this.saveFailed}
 }
 async persistArchive(){
  if(this.directoryHandle){
   const filename=`drive-${this.epoch}.zip`;
   const file=await this.directoryHandle.getFileHandle(filename,{create:true});
   const writable=await file.createWritable();
   try{await writable.write(this.archive);await writable.close()}
   catch(error){await writable.abort();throw error}
   this.saveFailed=false;this.status.textContent=`Saved ${filename} to ${this.directoryHandle.name}.`;
   return
  }
  this.download();this.saveFailed=false;this.status.textContent='Recording downloaded. Use Save again if needed.';
 }
 download(){if(!this.archive)return;const url=URL.createObjectURL(this.archive),a=document.createElement('a');a.href=url;a.download=`drive-${this.epoch}.zip`;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000)}
}
