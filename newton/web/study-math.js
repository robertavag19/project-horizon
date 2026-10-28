/* Trusted local mechanics templates. No generated code or expression evaluation. */
'use strict';
const StudyMath = {
  motion(p) {
    for (const key of ['position','velocity','acceleration']) if (!Number.isFinite(p[key]) || Math.abs(p[key])>100) throw Error('Invalid motion parameter');
    if (!Number.isFinite(p.duration) || p.duration<.1 || p.duration>60) throw Error('Invalid duration');
    return Array.from({length:61},(_,i)=>{const t=p.duration*i/60;return {t,x:p.position+p.velocity*t+.5*p.acceleration*t*t,v:p.velocity+p.acceleration*t,a:p.acceleration};});
  },
  circular(p) {
    if (![p.speed,p.radius,p.angle].every(Number.isFinite) || p.speed<0 || p.speed>30 || p.radius<.1 || p.radius>30 || p.angle<0 || p.angle>360) throw Error('Invalid circular parameter');
    const angle=p.angle*Math.PI/180,c=Math.cos(angle),s=Math.sin(angle),a=p.speed*p.speed/p.radius;
    return {point:[p.radius*c,p.radius*s],velocity:[-p.speed*s,p.speed*c],acceleration:[-a*c,-a*s],magnitude:a};
  }
};
if (typeof module !== 'undefined') module.exports=StudyMath;
