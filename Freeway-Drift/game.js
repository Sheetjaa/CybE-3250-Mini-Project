'use strict';
const canvas=document.getElementById('world'),ctx=canvas.getContext('2d'),map=document.getElementById('map'),mc=map.getContext('2d');
const $=id=>document.getElementById(id),TAU=Math.PI*2,CELL=310,ROAD=88,LIMIT=1550;
const cars=[{name:'THE DAILY',kind:'BALANCED & NIMBLE',color:'#d6a44d',roof:'#ebbd69',max:205,accel:100,grip:7.8,turn:2.3,length:33,width:17},{name:'THE WEEKENDER',kind:'LOW & LIVELY',color:'#c9735e',roof:'#e39678',max:270,accel:125,grip:5.3,turn:2.55,length:38,width:18},{name:'THE EXPLORER',kind:'STEADY & EASYGOING',color:'#7c9d96',roof:'#aac1b1',max:175,accel:75,grip:8.5,turn:1.85,length:40,width:20}];
let selected=0,running=false,started=false,W=innerWidth,H=innerHeight,zoom=1,trafficOn=true,automatic=false,soundOn=false;
let cam={x:0,y:0},car={x:0,y:30,a:-Math.PI/2,vx:0,vy:0,steer:0},keys={},buildings=[],trees=[],props=[],traffic=[],particles=[],skids=[],clock=0,last=0,impactCooldown=0;
let rngState=8224;function rnd(){rngState=(rngState*1664525+1013904223)>>>0;return rngState/4294967296}const pick=a=>a[Math.floor(rnd()*a.length)];
let recorder=null,simulationTime=0,segment=0;
const inputSources=new Map(),driveKeys=new Set(['w','a','s','d','arrowup','arrowdown','arrowleft','arrowright',' ']);
function setKey(key,down,source='keyboard',code=null,reason=null){
 const id=source+':'+(code||key),previous=inputSources.get(id);
 if(down&&previous||!down&&!previous)return;
 if(down)inputSources.set(id,{key,source,code});else{key=previous.key;inputSources.delete(id)}
 keys[key]=Array.from(inputSources.values()).some(input=>input.key===key);
 recorder?.event(down?'keydown':'keyup',{key,code,source,synthetic:reason!==null,reason,keys_held:Object.keys(keys).filter(k=>keys[k]).sort()});
}
function clearKeys(reason){for(const input of Array.from(inputSources.values()))setKey(input.key,false,input.source,input.code,reason);keys={}}
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));const approach=(a,b,t)=>a+(b-a)*Math.min(1,t);
function roadDist(v){return Math.abs(v-Math.round(v/CELL)*CELL)}
function onRoad(x,y){return roadDist(x)<ROAD/2||roadDist(y)<ROAD/2}
function generate(){
 for(let gx=-5;gx<5;gx++)for(let gy=-5;gy<5;gy++){
  let x=gx*CELL+ROAD/2+17,y=gy*CELL+ROAD/2+17,park=(gx===0&&gy===0)||rnd()<.18;
  if(park){for(let i=0;i<8;i++)trees.push({x:x+20+rnd()*150,y:y+20+rnd()*150,s:12+rnd()*8});continue}
  for(let bx=0;bx<2;bx++)for(let by=0;by<2;by++){
   let w=60+rnd()*20,d=60+rnd()*20; buildings.push({x:x+bx*98,y:y+by*98,w,d,h:16+rnd()*55,c:pick(['#d3c5aa','#d3d5bf','#c1c9b0','#d9c9ad','#c6bcad','#e0d3b8']),roof:pick(['#e3dac4','#e3dfca','#d7d9c4','#c6cbb9'])});
  }
  for(let i=0;i<3;i++)trees.push({x:x+i*68+5,y:y-8,s:11+rnd()*6});
 }
 for(let i=-5;i<=5;i++)for(let j=-5;j<5;j++){
  props.push({x:i*CELL+55,y:j*CELL+125,type:'lamp'});
  props.push({x:i*CELL-55,y:j*CELL+175,type:'bench'});
 }
 for(let i=0;i<25;i++){let axis=i%2,dir=i%4<2?1:-1,lane=(Math.floor(rnd()*9)-4)*CELL;
  traffic.push({axis,dir,lane,pos:(rnd()*2-1)*LIMIT,speed:48+rnd()*35,c:pick(['#d9bb79','#8eaaa4','#b9c1a9','#bf8e7b','#e5d8bf']),stop:0})}
}
generate();
function resize(){W=innerWidth;H=innerHeight;const dpr=Math.min(devicePixelRatio||1,2);canvas.width=Math.round(W*dpr);canvas.height=Math.round(H*dpr);canvas.style.width=W+'px';canvas.style.height=H+'px';ctx.setTransform(dpr,0,0,dpr,0,0);zoom=clamp(Math.min(W/1100,H/760),.72,1.6)}
addEventListener('resize',resize);resize();
function project(x,y,z=0){const dx=x-cam.x,dy=y-cam.y;return {x:(dx-dy)*.866*zoom+W*(running?.5:.71),y:(dx+dy)*.5*zoom-z*zoom+H*.49}}
function polygon(points,color,stroke){ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));ctx.closePath();ctx.fillStyle=color;ctx.fill();if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=.7;ctx.stroke()}}
function groundRect(x,y,w,d,color,z=0){polygon([project(x,y,z),project(x+w,y,z),project(x+w,y+d,z),project(x,y+d,z)],color)}
function shade(color,f){let n=parseInt(color.slice(1),16),rgb=color.startsWith('#')?[n>>16,(n>>8)&255,n&255]:color.match(/[\d.]+/g).slice(0,3).map(Number);return `rgb(${rgb.map(v=>clamp(Math.round(v*f),0,255)).join(',')})`}
function box(x,y,w,d,h,c,roof,z=0){let p=[project(x,y,z),project(x+w,y,z),project(x+w,y+d,z),project(x,y+d,z)],t=[project(x,y,z+h),project(x+w,y,z+h),project(x+w,y+d,z+h),project(x,y+d,z+h)];polygon([p[1],p[2],t[2],t[1]],shade(c,.83));polygon([p[2],p[3],t[3],t[2]],c);polygon(t,roof||shade(c,1.07))}
function drawBuilding(b){
 groundRect(b.x+8,b.y+8,b.w+12,b.d+12,'#526a4627');box(b.x,b.y,b.w,b.d,b.h,b.c,b.roof);
 box(b.x+5,b.y+5,b.w-10,b.d-10,2,shade(b.roof,.91),b.roof,b.h);
 if(b.h>37){for(let j=10;j<b.h-5;j+=16)for(let i=12;i<b.w-8;i+=19){polygon([project(b.x+i,b.y+b.d+.1,j),project(b.x+i+7,b.y+b.d+.1,j),project(b.x+i+7,b.y+b.d+.1,j+8),project(b.x+i,b.y+b.d+.1,j+8)],'#7e969080')}
 for(let j=10;j<b.h-5;j+=16)for(let i=12;i<b.d-8;i+=19){polygon([project(b.x+b.w+.1,b.y+i,j),project(b.x+b.w+.1,b.y+i+7,j),project(b.x+b.w+.1,b.y+i+7,j+8),project(b.x+b.w+.1,b.y+i,j+8)],'#627e7775')}}
 box(b.x+b.w*.52,b.y+b.d*.24,14,17,5,'#b3b8a8','#c6ccbb',b.h+2);
}
function drawTree(t){groundRect(t.x-5,t.y-4,t.s+13,t.s+11,'#39543e22');box(t.x-2,t.y-2,4,4,12,'#8d8161');box(t.x-t.s/2,t.y-t.s/2,t.s,t.s,t.s*.8,'#7e9c67','#99b27b',10);box(t.x-t.s*.33,t.y-t.s*.33,t.s*.66,t.s*.66,t.s*.48,'#8da96f','#a9bf88',10+t.s*.8)}
function drawProp(p){if(p.type==='lamp'){box(p.x,p.y,2,2,34,'#98a390','#b7c0aa');box(p.x-1,p.y-3,4,7,3,'#bcc5af','#eee9cc',34)}else{box(p.x,p.y,6,21,5,'#a18c6b','#bea986');box(p.x+5,p.y,2,21,8,'#a18c6b','#bea986',4)}}
function carBox(v,l,w,h,z,color,roof,ox=0){let ca=Math.cos(v.a),sa=Math.sin(v.a);let pos=(x,y,zz)=>project(v.x+(x+ox)*ca-y*sa,v.y+(x+ox)*sa+y*ca,zz);let corners=[[-l/2,-w/2],[l/2,-w/2],[l/2,w/2],[-l/2,w/2]],p=corners.map(q=>pos(...q,z)),t=corners.map(q=>pos(...q,z+h));for(let i=0;i<4;i++){let j=(i+1)%4;let nx=(corners[i][0]+corners[j][0])/2,ny=(corners[i][1]+corners[j][1])/2;let depth=nx*(ca+sa)+ny*(ca-sa);if(depth>0)polygon([p[i],p[j],t[j],t[i]],shade(color,i%2?.84:1))}polygon(t,roof||color)}
function drawCar(v,model,isPlayer=false){
 let p=project(v.x,v.y);ctx.save();ctx.translate(p.x+5,p.y+5);ctx.scale(1,.51);ctx.beginPath();ctx.ellipse(0,0,22*zoom,16*zoom,0,0,TAU);ctx.fillStyle='#263c3a30';ctx.fill();ctx.restore();
 for(let x of [-model.length*.30,model.length*.29])for(let y of [-model.width*.5,model.width*.5]){let ca=Math.cos(v.a),sa=Math.sin(v.a);carBox({x:v.x+x*ca-y*sa,y:v.y+x*sa+y*ca,a:v.a},8,4,5,2,'#36453f','#43514a')}
 carBox(v,model.length,model.width,7,4,model.color,model.roof);carBox(v,model.length*.48,model.width*.81,6,11,'#456862','#b8cbc0',-2);
 carBox(v,model.length*.29,model.width*.86,1,17,model.roof,model.roof,-3);
 for(let side of [-1,1]){let ca=Math.cos(v.a),sa=Math.sin(v.a);let light=(x,c)=>carBox({x:v.x+x*ca-side*model.width*.31*sa,y:v.y+x*sa+side*model.width*.31*ca,a:v.a},2,4,3,7,c,c);light(model.length/2,'#f3ecc9');light(-model.length/2,keys.s||keys.arrowdown?'#f15c44':'#b36b50')}
 if(isPlayer&&!running){let q=project(v.x,v.y,45+Math.sin(clock*2)*3);polygon([{x:q.x-5,y:q.y-5},{x:q.x+5,y:q.y-5},{x:q.x,y:q.y+1}],'#f5f3e9')}
}
function trafficPose(t){return t.axis===0?{x:t.pos,y:t.lane+t.dir*20,a:t.dir===1?0:Math.PI}:{x:t.lane-t.dir*20,y:t.pos,a:t.dir===1?Math.PI/2:-Math.PI/2}}
function visible(x,y,margin=130){let p=project(x,y);return p.x>-margin&&p.x<W+margin&&p.y>-margin&&p.y<H+margin}
function draw(){
 ctx.fillStyle='#b6c79f';ctx.fillRect(0,0,W,H);
 groundRect(-LIMIT-95,-LIMIT-95,LIMIT*2+190,LIMIT*2+190,'#a9bc96');
 for(let i=-5;i<=5;i++){
  groundRect(i*CELL-ROAD/2-10,-LIMIT-55,ROAD+20,LIMIT*2+110,'#d8d8be');groundRect(-LIMIT-55,i*CELL-ROAD/2-10,LIMIT*2+110,ROAD+20,'#d8d8be');
 }
 for(let i=-5;i<=5;i++){
  groundRect(i*CELL-ROAD/2,-LIMIT-44,ROAD,LIMIT*2+88,'#87958a');groundRect(-LIMIT-44,i*CELL-ROAD/2,LIMIT*2+88,ROAD,'#87958a');
 }
 for(let i=-5;i<=5;i++)for(let j=-5;j<5;j++){
  for(let n=75;n<260;n+=39){let x=i*CELL,y=j*CELL+n;if(visible(x,y,20))groundRect(x-1,y,2,16,'#d7dac16b');if(visible(y,x,20))groundRect(y,x-1,16,2,'#d7dac16b')}
  for(let k=-27;k<30;k+=12){if(visible(i*CELL,j*CELL+55,30))groundRect(i*CELL+k,j*CELL+48,7,10,'#d9ddc387');if(visible(j*CELL+55,i*CELL,30))groundRect(j*CELL+48,i*CELL+k,10,7,'#d9ddc387')}
 }
 // Walking paths and a quiet green at the center of town.
 groundRect(66,68,177,177,'#9db585');groundRect(66,149,177,12,'#d3d2b5');groundRect(149,68,12,177,'#d3d2b5');
 groundRect(130,130,50,50,'#c9cfb3');box(139,139,32,32,3,'#b8c5ad','#9dbfba');
 for(let s of skids){let a=project(s.x,s.y),b=project(s.x2,s.y2);ctx.strokeStyle=`rgba(43,58,46,${s.life*.035})`;ctx.lineWidth=2.2*zoom;ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke()}
 let entities=[];for(let b of buildings)if(visible(b.x+b.w/2,b.y+b.d/2))entities.push({depth:b.x+b.y+(b.w+b.d)*.5,draw:()=>drawBuilding(b)});
 for(let t of trees)if(visible(t.x,t.y))entities.push({depth:t.x+t.y,draw:()=>drawTree(t)});
 for(let p of props)if(visible(p.x,p.y,50))entities.push({depth:p.x+p.y,draw:()=>drawProp(p)});
 if(trafficOn)for(let t of traffic){let v=trafficPose(t);if(visible(v.x,v.y,50))entities.push({depth:v.x+v.y,draw:()=>drawCar(v,{length:32,width:16,color:t.c,roof:shade(t.c,1.07)})})}
 entities.push({depth:car.x+car.y,draw:()=>drawCar(car,cars[selected],true)});entities.sort((a,b)=>a.depth-b.depth);entities.forEach(e=>e.draw());
 // A subtle outline locates the car if a building blocks the camera.
 let cp=project(car.x,car.y);ctx.strokeStyle='#eff5d8a0';ctx.lineWidth=1;ctx.beginPath();ctx.ellipse(cp.x,cp.y+4,22*zoom,11*zoom,0,0,TAU);ctx.stroke();
 for(let p of particles){let q=project(p.x,p.y,p.z);ctx.globalAlpha=p.life/p.max;ctx.fillStyle=p.c;ctx.fillRect(q.x,q.y,p.size*zoom,p.size*zoom)}ctx.globalAlpha=1;
}
function collision(x,y,r){for(let b of buildings){let nx=clamp(x,b.x,b.x+b.w),ny=clamp(y,b.y,b.y+b.d);if((x-nx)**2+(y-ny)**2<r*r)return true}return Math.abs(x)>LIMIT+34||Math.abs(y)>LIMIT+34}
function puff(x,y,n,c){for(let i=0;i<n;i++)particles.push({x,y,z:4+Math.random()*5,vx:(Math.random()-.5)*40,vy:(Math.random()-.5)*40,life:.3+Math.random()*.5,max:.8,c,size:2+Math.random()*4})}
function step(dt){
 let m=cars[selected],forward=car.vx*Math.cos(car.a)+car.vy*Math.sin(car.a),speed=Math.hypot(car.vx,car.vy),gas=keys.w||keys.arrowup||automatic,brake=keys.s||keys.arrowdown,handbrake=keys[' '],steering=(keys.d||keys.arrowright?1:0)-(keys.a||keys.arrowleft?1:0);
 car.steer=approach(car.steer,steering,dt*9);
 if(brake){if(forward>5){car.vx*=Math.max(0,1-dt*3.4);car.vy*=Math.max(0,1-dt*3.4)}else{car.vx-=Math.cos(car.a)*m.accel*.55*dt;car.vy-=Math.sin(car.a)*m.accel*.55*dt}}
 else if(gas){car.vx+=Math.cos(car.a)*m.accel*dt;car.vy+=Math.sin(car.a)*m.accel*dt}
 car.a+=car.steer*m.turn*clamp(Math.abs(forward)/52,0,1)*(forward<-.5?-1:1)*(handbrake?1.25:1)*dt;
 let ca=Math.cos(car.a),sa=Math.sin(car.a),f=car.vx*ca+car.vy*sa,side=-car.vx*sa+car.vy*ca,grass=!onRoad(car.x,car.y);
 side*=Math.exp(-(handbrake?1.0:m.grip)*dt);f*=Math.exp(-(handbrake?1.1:grass?1.0:.28)*dt);f=clamp(f,-65,m.max*(grass?.65:1));
 car.vx=f*ca-side*sa;car.vy=f*sa+side*ca;
 let oldX=car.x,oldY=car.y,nx=car.x+car.vx*dt,ny=car.y+car.vy*dt,hit=false;
 if(!collision(nx,car.y,12))car.x=nx;else{car.vx*=-.26;hit=true}
 if(!collision(car.x,ny,12))car.y=ny;else{car.vy*=-.26;hit=true}
 if(hit&&speed>30&&impactCooldown<=0){puff(car.x,car.y,12,'#dfd4b2');impactCooldown=.4}
 if(speed>45&&(Math.abs(side)>20||handbrake)){
  for(let sign of [-1,1]){let ox=sign*7*sa-11*ca,oy=-sign*7*ca-11*sa;skids.push({x:oldX+ox,y:oldY+oy,x2:car.x+ox,y2:car.y+oy,life:8})}
  if(Math.random()<.4)puff(car.x-15*ca,car.y-15*sa,1,'#dedfce');
 }
 if(grass&&speed>40&&Math.random()<.3)puff(car.x,car.y,1,'#c3c49e');
 impactCooldown-=dt;updateTraffic(dt,true);updateParticles(dt);
 cam.x=approach(cam.x,car.x+car.vx*.42,dt*4);cam.y=approach(cam.y,car.y+car.vy*.42,dt*4);
 updateAudio(speed,gas&&!brake);
}
function updateParticles(dt){for(let p of particles){p.life-=dt;p.x+=p.vx*dt;p.y+=p.vy*dt;p.z+=dt*9}particles=particles.filter(p=>p.life>0).slice(-160);for(let s of skids)s.life-=dt;skids=skids.filter(s=>s.life>0).slice(-700)}
function updateTraffic(dt,interact){if(!trafficOn)return;for(let t of traffic){let v=trafficPose(t),dx=car.x-v.x,dy=car.y-v.y,dist=Math.hypot(dx,dy),ahead=dx*Math.cos(v.a)+dy*Math.sin(v.a),across=Math.abs(-dx*Math.sin(v.a)+dy*Math.cos(v.a));let blocked=interact&&ahead>0&&ahead<85&&across<24;
  for(let other of traffic){if(other===t)continue;let ov=trafficPose(other),ox=ov.x-v.x,oy=ov.y-v.y,a=ox*Math.cos(v.a)+oy*Math.sin(v.a),s=Math.abs(-ox*Math.sin(v.a)+oy*Math.cos(v.a));if(a>0&&a<48&&s<20){blocked=true;break}}
  t.pos+=t.dir*t.speed*(blocked?0:1)*dt;if(t.pos>LIMIT+30)t.pos=-LIMIT-30;if(t.pos<-LIMIT-30)t.pos=LIMIT+30;
  if(interact&&dist<25&&dist>.01){let push=25-dist;let nx=car.x+dx/dist*push,ny=car.y+dy/dist*push;if(!collision(nx,ny,12)){car.x=nx;car.y=ny}car.vx*=.94;car.vy*=.94}
 }}
function updateHud(f,handbrake,grass){$('speed').textContent=Math.round(Math.abs(f)*.48);$('gear').textContent=Math.abs(f)<2?'N':f<0?'R':'D';$('speed-bar').style.width=Math.min(100,Math.abs(f)/cars[selected].max*100)+'%';$('drive-mode').textContent=handbrake?'HANDBRAKE':grass?'OFF THE BEATEN PATH':Math.abs(f)<3?'READY TO ROLL':automatic?'AUTO CRUISE':'TAKE THE LONG WAY';$('district').textContent=car.x<-450?'Westwood':car.x>450?'Eastside':car.y<-450?'North Park':car.y>450?'Garden District':'Cedar Quarter';drawMap()}
function drawMap(){let s=160/(LIMIT*2+170),mid=80;mc.fillStyle='#b3c59f';mc.fillRect(0,0,160,160);mc.fillStyle='#e2e4cd';for(let i=-5;i<=5;i++){mc.fillRect(mid+(i*CELL-ROAD/2)*s,0,ROAD*s,160);mc.fillRect(0,mid+(i*CELL-ROAD/2)*s,160,ROAD*s)}mc.fillStyle='#8fa381';for(let b of buildings)mc.fillRect(mid+b.x*s,mid+b.y*s,b.w*s,b.d*s);mc.save();mc.translate(mid+car.x*s,mid+car.y*s);mc.rotate(car.a);mc.fillStyle='#273e36';mc.strokeStyle='#f5f3e9';mc.lineWidth=1.5;mc.beginPath();mc.moveTo(7,0);mc.lineTo(-4,4);mc.lineTo(-2,0);mc.lineTo(-4,-4);mc.closePath();mc.fill();mc.stroke();mc.restore()}
function reset(){clearKeys('reset');car={x:0,y:30,a:-Math.PI/2,vx:0,vy:0,steer:0};cam={x:car.x,y:car.y};segment++;recorder?.event('reset',{segment});if(running)toast('Back on the road.');}
let toastTimer;function toast(s){$('toast').textContent=s;$('toast').classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').classList.remove('show'),2400)}
function setRunning(value,reason='pause'){clearKeys(value?'resume':reason);if(!value)recorder?.stop(reason);running=value;$('menu').classList.toggle('hidden',running);$('driving').classList.toggle('hidden',!running);document.body.classList.toggle('menu-open',!running);if(running){started=true;$('start').innerHTML='Continue driving <span>↗</span>';if(soundOn)initAudio();canvas.focus()}else{if(engineGain)engineGain.gain.setTargetAtTime(0,audio.currentTime,.08)} }
document.querySelectorAll('.car-choice').forEach(btn=>btn.addEventListener('click',()=>{selected=Number(btn.dataset.car);car.vx=car.vy=0;document.querySelectorAll('.car-choice').forEach(b=>{b.classList.toggle('selected',b===btn);b.setAttribute('aria-pressed',String(b===btn))});$('car-kind').textContent=cars[selected].kind;$('ride-name').textContent=cars[selected].name}));
$('traffic').addEventListener('change',e=>trafficOn=e.target.checked);$('auto').addEventListener('change',e=>automatic=e.target.checked);
$('start').addEventListener('click',()=>setRunning(true));$('pause').addEventListener('click',()=>setRunning(false));$('home').addEventListener('click',e=>{e.preventDefault();setRunning(false)});
$('fullscreen').addEventListener('click',async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen()}catch{toast('Use your browser’s fullscreen shortcut: F11.')}});
addEventListener('keydown',e=>{
 if(e.target instanceof HTMLInputElement||e.target instanceof HTMLTextAreaElement||e.target.isContentEditable)return;
 const k=e.key.toLowerCase();if(driveKeys.has(k)&&running)e.preventDefault();
 if(e.repeat)return;
 if(k==='escape'){recorder?.event('command',{key:k,code:e.code,action:'pause'});setRunning(!running&&started);return}
 if(k==='r'&&running){recorder?.event('command',{key:k,code:e.code,action:'reset'});reset();return}
 if(running&&driveKeys.has(k))setKey(k,true,'keyboard',e.code);
});
addEventListener('keyup',e=>setKey(e.key.toLowerCase(),false,'keyboard',e.code));
addEventListener('blur',()=>{if(running)setRunning(false,'blur')});document.addEventListener('visibilitychange',()=>{if(document.hidden&&running)setRunning(false,'hidden')});
for(let b of document.querySelectorAll('[data-key]')){b.addEventListener('pointerdown',e=>{e.preventDefault();if(!running)return;b.setPointerCapture(e.pointerId);setKey(b.dataset.key,true,'pointer:'+e.pointerId)});for(let evt of ['pointerup','pointercancel','lostpointercapture'])b.addEventListener(evt,e=>setKey(b.dataset.key,false,'pointer:'+e.pointerId))}
let audio,engine,engineGain,filter;function initAudio(){if(!audio){const AC=window.AudioContext||window.webkitAudioContext;if(!AC){toast('Engine sound is unavailable in this browser.');return}audio=new AC();engine=audio.createOscillator();engine.type='sawtooth';filter=audio.createBiquadFilter();filter.type='lowpass';filter.frequency.value=210;engineGain=audio.createGain();engineGain.gain.value=0;engine.connect(filter);filter.connect(engineGain);engineGain.connect(audio.destination);engine.start()}audio.resume()}
function updateAudio(speed,gas){if(!audio||!engineGain)return;engine.frequency.setTargetAtTime(35+speed*.48+(gas?12:0),audio.currentTime,.1);filter.frequency.setTargetAtTime(130+speed*1.2,audio.currentTime,.1);engineGain.gain.setTargetAtTime(soundOn&&running?.025+(gas?.012:0):0,audio.currentTime,.1)}
$('sound').addEventListener('click',()=>{soundOn=!soundOn;if(soundOn)initAudio();$('sound').querySelector('.sound-slash').style.display=soundOn?'none':'block';$('sound').setAttribute('aria-label',soundOn?'Mute engine sound':'Enable engine sound');if(!soundOn&&engineGain)engineGain.gain.setTargetAtTime(0,audio.currentTime,.1)});
recorder=new DrivingRecorder(canvas,()=>({running,simulation_time_s:simulationTime,segment,keys_held:Object.keys(keys).filter(k=>keys[k]).sort(),actions:{accelerate:!!(keys.w||keys.arrowup||automatic),brake_reverse:!!(keys.s||keys.arrowdown),steering:(keys.d||keys.arrowright?1:0)-(keys.a||keys.arrowleft?1:0),handbrake:!!keys[' ']},car:{...car,model:cars[selected].name},camera:{...cam,zoom},settings:{traffic:trafficOn,auto_accelerate:automatic},viewport:{width:W,height:H}}));
function frame(t){let dt=Math.min((t-last)/1000||0,.05);last=t;clock+=dt;if(running){simulationTime+=dt;let n=Math.ceil(dt/.012);for(let i=0;i<n;i++)step(dt/n);updateHud(car.vx*Math.cos(car.a)+car.vy*Math.sin(car.a),keys[' '],!onRoad(car.x,car.y))}else if(!started){updateTraffic(dt,false)}draw();recorder.tick();requestAnimationFrame(frame)}
setRunning(false);requestAnimationFrame(frame);
