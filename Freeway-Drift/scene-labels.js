'use strict';
// Coordinates: forward along the car heading; right is positive lateral distance.
function sceneCorners(pose,length,width){
 const c=Math.cos(pose.a),s=Math.sin(pose.a);
 return [[-length/2,-width/2],[length/2,-width/2],[length/2,width/2],[-length/2,width/2]].map(([f,r])=>({x:pose.x+f*c-r*s,y:pose.y+f*s+r*c}));
}
function sceneClip(points,key,bound,sign){
 const out=[];
 for(let i=0;i<points.length;i++){
  const a=points[i],b=points[(i+1)%points.length],da=(a[key]-bound)*sign,db=(b[key]-bound)*sign;
  if(da>=0)out.push(a);
  if((da>=0)!==(db>=0)){
   const t=da/(da-db);out.push({forward:a.forward+t*(b.forward-a.forward),right:a.right+t*(b.right-a.right)});
  }
 }
 return out;
}
function sceneOverlap(points,f0,f1,r0,r1){
 let p=points;
 for(const [key,bound,sign] of [['forward',f0,1],['forward',f1,-1],['right',r0,1],['right',r1,-1]])p=sceneClip(p,key,bound,sign);
 // Require positive area: touching a zone edge alone does not block it.
 return Math.abs(p.reduce((area,a,i)=>{const b=p[(i+1)%p.length];return area+a.forward*b.right-b.forward*a.right},0))>1e-7;
}
function labelScene(player,obstacles,config,projectPoint,viewport){
 const c=Math.cos(player.a),s=Math.sin(player.a),start=player.length/2;
 const labels={obstacle_left:false,obstacle_center:false,obstacle_right:false};
 const zones=[['left',-1],['center',0],['right',1]].map(([name,lane])=>({name,forward_min:start,forward_max:start+config.distance,right_min:(lane-.5)*config.lane_width,right_max:(lane+.5)*config.lane_width}));
 const objects=obstacles.map(o=>{
  const corners=sceneCorners(o,o.length,o.width);
  const relative=corners.map(p=>{const dx=p.x-player.x,dy=p.y-player.y;return {forward:dx*c+dy*s,right:-dx*s+dy*c}});
  const lanes=zones.filter(z=>sceneOverlap(relative,z.forward_min,z.forward_max,z.right_min,z.right_max)).map(z=>z.name);
  for(const lane of lanes)labels['obstacle_'+lane]=true;
  const projected=corners.flatMap(p=>[projectPoint(p.x,p.y,0),projectPoint(p.x,p.y,o.height)]);
  const xs=projected.map(p=>p.x),ys=projected.map(p=>p.y);
  const raw={x_min:Math.min(...xs),y_min:Math.min(...ys),x_max:Math.max(...xs),y_max:Math.max(...ys)};
  const visible=raw.x_max>0&&raw.y_max>0&&raw.x_min<viewport.width&&raw.y_min<viewport.height;
  const bbox=visible?{x_min:Math.max(0,raw.x_min)/viewport.width,y_min:Math.max(0,raw.y_min)/viewport.height,x_max:Math.min(viewport.width,raw.x_max)/viewport.width,y_max:Math.min(viewport.height,raw.y_max)/viewport.height}:null;
  return {...o,lanes,relative_center:{forward:(o.x-player.x)*c+(o.y-player.y)*s,right:-(o.x-player.x)*s+(o.y-player.y)*c},bbox_normalized:bbox};
 });
 return {labels,active_labels:Object.keys(labels).filter(k=>labels[k]),config:{...config},zones,obstacles:objects};
}
