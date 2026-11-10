(function(){
const DATA=window.SOFC_SENSORS;
// Stage keys stay the plant-data stage names (sensors.js fits/flows and bends.js borders are keyed by them). Since v3.0
// (2026-11-06, user) the twin SHOWS them as: Heat up = Heat-up air → Heat-up N₂+H₂ (its end, the forming-gas "Hot standby" key,
// lasts one minute: the twin opens the gas there); Hot standby = the "Fuel switch" key (natural gas on, no current, no power drawn);
// Part load; Rated power (new key, no plant data); Air flow cooling; Shutdown; Trip. Part load and rated power only by button.
const HU="#E8B04A";
const STAGES={"Heat-up air":HU,"Heat-up N₂+H₂":HU,"Hot standby":HU,"Fuel switch":"#B4472B","Part load":"#2E8B57","Rated power":"#7B4FA0","Air-flow cooling":"#3A7CA5","Shutdown":"#8C96A3","Trip: purge":"#C2185B"};
// Display names: the trip stage is shown as "Trip / Emergency purge". Data keys stay "Trip: purge".
const NAME={"Trip: purge":"Trip / Emergency purge","Heat-up air":"Heat up","Heat-up N₂+H₂":"Heat up","Hot standby":"Heat up","Fuel switch":"Hot standby","Air-flow cooling":"Air flow cooling"}, nm=st=>NAME[st]||st;
// with the heat-up phase (stage pill, bend panel): "Heat up · air", "Heat up · N₂+H₂", "Heat up · N₂+H₂ end"
const PHASE={"Heat-up air":"air","Heat-up N₂+H₂":"N₂+H₂","Hot standby":"N₂+H₂ end"}, nmp=st=>PHASE[st]?`${nm(st)} · ${PHASE[st]}`:nm(st);
const T_AMB=25, AIR_COOL=20, T_FORMING=210, I_POWER=1, NG_ON=20, N2_ON=100, H2_ON=5;
const FLOWS=DATA.flows;

// ---------- model ----------
// Stack heat balance, fitted on the 39 days with the 8 replay stretches held out:
//   dT/dt [°C/h] = k·(Tin − T) + heaters + fuel + current − loss
// 1 air exchange per hour at 6000 ln/min, ∝ air^1.5: 0.56 when the air warms the stack, 0.32 when it cools it
//   (the insulated hot box gives back stored heat while cooling; one heat tank cannot hold both). 0.58 cooling at 9000.
// 2 air-in Tin = recuperator (APH re-uses the flue heat): 25 + e·(T − 25), e 0.88 at 6000 → 0.83 at 8000+ ln/min;
//   heaters on: the air heater lifts it towards its target at the plant's 60 °C/h outlet ramp, max 40 kW.
//   Otherwise Tin follows with a 10-min lag. Checked on measured TIRC 2.06: median miss 0–4 °C per stage.
// 3 fuel heat 0.370 °C/h per ln/min natural gas (fuel switch, 0 A).
// 4 current 6.61 °C/h per A per string (part load, after the fuel heat). Hot-box heaters 7.6 °C/h, loss 0.0121/h (air-off shutdown).
// Fitted numbers are re-made by 03_data_analysis/scripts/twin_fits.py (→ 03_data_analysis/twin_fits/); Q_NG/Q_PER_A/ETA_EAPH
// refitted 2026-11-05 on the rebuilt stage file (were 0.386 / 6.34 / 0.89). E_REC/E_REC_HI are hand-set (beat the refit on the replays).
const K_UP=0.561, K_DOWN=0.316, AIR_EXP=1.5, E_REC=0.88, E_REC_HI=0.83, RAMP=60, RISE_6000=268, Q_HEAT=7.62, Q_NG=0.370, Q_PER_A=6.61, LOSS=0.0121, TAU_H=10/60;
// Part load check (2026-11-04) on the 10 plant part-load runs (8–44 min, plant knobs in): mean stack miss 4.2 °C.
// The plant's air heater stays on in fuel switch and part load and holds the air-in at its target (580 / 600 °C),
// also when the recuperator delivers hotter air (heater on: air-in − target median 0 K): the 3-way valve TWV-CA mixes in bypass air.
const SP_FS=580, SP_PL=600;                       // plant median air-heater targets (ct_TIRC_206_SP) in fuel switch / part load
// Stack keeper (twin only): the plant never ran part load longer than 44 min, so its own way of holding the stack is not in the data.
// When on, above KEEP it raises the cathode air (+200 ln/min per min) to 10000, then lowers the air-heater target (−5 °C per min, min 500);
// below KEEP−5 it hands back (target, then air) to the settings it started from. 660 keeps the safety TC under ~700 (trip 720).
// Off by default since v3.0 (user, 2026-11-06: change nothing by temperature); the Stack keeper switch can still turn it on.
const KEEP=660, KEEP_BAND=5, KEEP_AIR=200, KEEP_SP=5, AIR_MAX=10000, SP_MIN=500, STACK_TRIP=720, STACK_SAFETY="TIRZ_8_1_3";
// Trip purge (by button only; a 720 °C stack-safety reading only warns) is allowed from hot standby, part load or rated power;
// elsewhere the Trip buttons are locked. After the purge the twin goes back to hot standby. Purge 16 min (plant purges 15–17 min).
// Part load and rated power are always followed by hot standby (part load may also go up to rated power, or a trip purge).
const PURGE_FROM=["Fuel switch","Part load","Rated power"], LOADS=["Part load","Rated power"], PURGE_MIN=16;
const SP_HS=500;   // heat-up air-heater target: the stack settles ~506 °C, where the heat up ends and the gas opens
// Shut down cools at 9000 ln/min and turns the air off at 40 °C (plant full cool-down after trip #8: air 9000, 664 → 41 °C in 18 h).
const SD_AIR=9000, AIR_OFF_T=40;
// Rated power (v3.3): 30 A per string (user, 2026-11-06; v3.0–3.2 used 40.18 A = 60 kW). The plant never went above
// 16.2 A / 34 kW, so there is no plant data: 30 A on all strings gives 52.0 kW on the string V–I lines (VI below,
// string_vi_fit.csv; El.Load 4.1–4.5 rated 42 A / 14 kW each, 01_docs/component_sensor_map_en.md). NG and POx are the
// sensors' rated values from the part-load extrapolation (data/sensors.js "rated" = sensor_extrapolation.csv use_rated,
// 52 kW: NG 180 ln/min by Faraday at the fuel-use trend, POx 202 ln/min on its best-fitting curve). Cells then average
// 0.73 V (weakest string 0.67 V), around the plant's 0.72 V minimum-cell limit: the twin does not act on it.
// Air 10000 (plant max; the extrapolation asks more, past the blower), air heater as part load. Rated power holds until a button is pressed (user, 2026-11-06), and the
// twin changes nothing by temperature there: no stack keeper, no automatic 720 °C trip. The heat balance runs as fitted, so
// the stack goes where the physics takes it.
// The stage reads Rated power above the plant's highest part-load current (16.2 A).
const I_RATED_MIN=17;
const RATED_V=col=>Object.values(DATA.components).flat().find(r=>r.col===col)?.rated?.v;
FLOWS["Rated power"]={...FLOWS["Part load"],air:AIR_MAX,12:RATED_V("ct_FIRC_12_PV_ProcessValue"),14:RATED_V("ct_FIRC_14_PV_ProcessValue"),I:30};
const S={t:0,T:T_AMB,Tin:T_AMB,dT:0,slope:0,air:0,pox:0,n2:0,h2:0,ng:0,I:0,heaters:false,target:500,fgAuto:true,trip:0,mark:0,keeper:false,kept:false,plantCool:true,coolAt:null,lastSt:"Shutdown",hist:[]};
const ngOn=s=>s.ng>NG_ON, fgOn=s=>s.n2>N2_ON&&s.h2>H2_ON, heatOn=s=>s.heaters&&s.trip<=0, loadOn=s=>ngOn(s)&&s.I>=I_POWER;
// EAPH inlet = air leaving the recuperators (fitted 2026-11-04 on the 39 days, 8 replay stretches held out:
// inlet TIR 2.05 miss 23.5 → 12.6 °C). It follows 25 + e·(T − 25) with a 32-min lag (e 0.85 at 6000 → 0.87 at 9000 ln/min;
// the recuperators are heavy, so they lag the stack while it warms or cools), plus a gas gain of 0.85 °C per ln/min natural gas
// that builds up and fades with a 32-min lag (with gas on, the exhaust burner runs hotter and so does the recuperated air).
const REC_E6=0.8515, REC_E9=0.872, REC_TAU=32.4, REC_G=0.852, REC_TG=31.8, ETA_EAPH=0.909, EAPH_MAX=40;
// The stack heat balance keeps its own recuperator formula (REC_PHYS=false): tested 2026-11-04, the lagged recuperator inside the
// heat balance keeps the air warm while the stack cools and the 9000-air cooling replay misses 156 instead of 74 °C (others unchanged).
const REC_PHYS=false;
const recBase=s=>T_AMB+(REC_E6-(REC_E6-REC_E9)*Math.min(1,Math.max(0,(s.air-6000)/3000)))*(s.T-T_AMB);
const recNow=s=>s.Rb==null? recBase(s): s.Rb+s.Rg;
function followRec(s,h){
  if(s.Rb==null){ s.Rb=recBase(s); s.Rg=0; }
  s.Rb+=(recBase(s)-s.Rb)*(1-Math.exp(-h*60/REC_TAU));
  s.Rg+=(REC_G*Math.max(0,s.ng)-s.Rg)*(1-Math.exp(-h*60/REC_TG));
}
const tRec=s=>REC_PHYS? recNow(s): T_AMB+(E_REC-(E_REC-E_REC_HI)*Math.min(1,Math.max(0,(s.air-6000)/2000)))*(s.T-T_AMB);
// EAPH readings from the model (2026-11-04): outlet TIRC 2.06 = air-in Tin; inlet TIR 2.05 = recuperator air (the heater
// cannot cool, so with heaters on it is at most the outlet); power = air flow × cp × (outlet − inlet) ÷ 0.909
// (plant: 89–91 % of the electric power goes into the air; per-minute miss 0.6 kW, ~3 kW low in fuel switch / part load).
const eaphIn=s=>heatOn(s)? Math.min(recNow(s),s.Tin): recNow(s);
function eaphPower(s){
  if(!heatOn(s)||s.air<=AIR_COOL) return 0;
  const tin=eaphIn(s), cp=1003+0.1*(s.Tin+tin)/2, q=s.air/60000*1.293*cp*(s.Tin-tin)/1000;
  return Math.min(EAPH_MAX,Math.max(0,q/ETA_EAPH));
}
function tinTarget(s){
  const rec=tRec(s);
  if(!heatOn(s)) return rec;
  const cap=rec+RISE_6000*6000/Math.max(s.air,1000);   // 40 kW air heater (≈91 % into the air)
  return Math.min(s.target,cap);                        // recuperator hotter than the target: TWV-CA bypass holds the target (plant)
}
function followTin(s,h){
  const tg=tinTarget(s);
  s.Tin+=(Math.min(tg,Math.max(tRec(s),s.Tin))-s.Tin)*(1-Math.exp(-h/TAU_H));   // recuperator / falling: lag
  if(heatOn(s)&&tg>s.Tin) s.Tin=Math.min(tg,s.Tin+RAMP*h);                       // air heater: 60 °C/h ramp
}
function rate(s){
  const a=s.air>AIR_COOL? Math.pow(s.air/6000,AIR_EXP):0, g=s.Tin-s.T;
  return a*(g>0?K_UP:K_DOWN)*g+(heatOn(s)?Q_HEAT:0)+(ngOn(s)?Q_NG*s.ng:0)+(loadOn(s)?Q_PER_A*s.I:0)-LOSS*(s.T-T_AMB);
}
// Hot standby → air-flow cooling at the PLANT's cooling slope (2026-11-04). Fitted on the POC hot-standby exits that were
// free cool-downs (2026-02-04, 02-16, 02-18 at 6000 ln/min, 03-04 at 8000, 03-20 at 10000; 4.5–12 h each, cut where the
// air heater came back on): stack slope [°C/h] = −f·C6·(air/6000)^N·u·(u/475)^Q, u = stack − 25 °C,
// f = 1 − e^(−t/TAU) (t = minutes since hot standby ended: the plant takes a few minutes to reach full cooling speed).
// Mean miss over those runs 6.1 °C (heat balance 12.2); each run left out of the fit in turn: 10.8 °C (Q fixed at 0.5; free Q 12.9,
// straight line Q=0 9.8 but 7.3 in-sample). 2026-03-30 (only 14 min hot standby straight after part load) cools faster: 53 °C off (heat balance 66).
// The runs never went below ~260 °C, so under HSC_HI the slope blends into the heat balance (heat balance only below HSC_LO).
// Used while the plant stays in air-flow cooling after hot standby (heaters off, air on, no gas); switch: S.plantCool.
const HSC_C6=0.0605, HSC_N=1.65, HSC_Q=0.5, HSC_TAU=4.2, HSC_HI=300, HSC_LO=250;
function hsCoolRate(s){
  // onset: minimum-jerk S-curve over 2·TAU (same mean delay as the fitted 1 − e^(−t/TAU), but no kink in the slope at the start)
  const u=Math.max(s.T-T_AMB,0), f=mj((s.t+1-s.coolAt)/(2*HSC_TAU));
  const plant=-f*HSC_C6*Math.pow(s.air/6000,HSC_N)*u*Math.pow(u/475,HSC_Q);
  const w=Math.min(1,Math.max(0,(s.T-HSC_LO)/(HSC_HI-HSC_LO)));
  return w*plant+(1-w)*rate(s);
}
const freeCooling=s=>s.trip<=0&&!heatOn(s)&&s.air>AIR_COOL&&!ngOn(s);
const mj=u=>{ u=Math.min(1,Math.max(0,u)); return u*u*u*(10-15*u+6*u*u); };   // minimum-jerk S-curve 0 → 1
// Restart during a cool-down (rule set 2026-11-04, user): while the plant cools down (air-flow cooling or shutdown, heaters off,
// no gas) and the stack is below hot standby (SP_HS 500 °C), Start plant (or the Heat-up air / Heat-up N₂+H₂ stage button)
// restarts the heat-up from the stack temperature it has now, no reset to ambient: below 210 °C → Heat-up air (air 6000, heaters
// on, air heater 300 °C), 210 °C and up → Heat-up N₂+H₂ (N₂ + H₂ by the 210 °C rule, air heater 500 °C).
// Plant (POC data, clean restarts 2026-01-31 at 176 °C, 02-17 at 192 °C, 03-20 at 460 °C): the air-heater ramp starts from the
// air-in value of that moment (ct_TIRC_206_SP_RampStartValue) at 60 °C/h, so the stack keeps cooling a little, then turns to
// heating over ~1 h. Smooth turn: for RS_D min the stack slope blends on a minimum-jerk curve from the cooling slope it had into
// the heat balance. RS_D = the plant's stage-border bend time (data/bends.js, slope going 10 → 90 %): cooling → heat-up air
// 22 min, cooling → heat-up N₂+H₂ 7 min; a minimum-jerk curve covers 10 → 90 % in 0.506 of its length → 43 / 14 min.
const BENDS=window.SOFC_BENDS||{borders:[],warm:[]};
const MJ_1090=0.506;
const bendD=(from,to,def)=>{ const e=BENDS.borders.find(x=>x.from===from&&x.to===to), b=e&&e.sig.stack&&e.sig.stack.bend; return b&&b[1]>b[0]? Math.round((b[1]-b[0])/MJ_1090): def; };
const RS_D={"Heat-up air":bendD("Air-flow cooling","Heat-up air",43),"Heat-up N₂+H₂":bendD("Air-flow cooling","Heat-up N₂+H₂",14)};
const coolingDown=s=>s.trip<=0&&!heatOn(s)&&!ngOn(s)&&s.I<I_POWER;
const canRestart=s=>coolingDown(s)&&s.T<SP_HS&&s.T-T_AMB>=1;
// Every stage change (2026-11-04, user: no sharp transitions): the knobs change in one step, so the heat balance would switch
// its heating rate in one minute (e.g. fuel switch → part load +35 → +100 °C/h). The plant turns over minutes. At any stage
// change where the rate would jump by more than BLEND_MIN, the stack slope blends (minimum-jerk) from the slope it had into the
// new one over that border's plant bend time (data/bends.js, stack, 10 → 90 %) ÷ 0.506; border types with no clear plant bend
// use the median of the clear ones. Not on stage-bar jumps (a teleport) and not where the plant cooling law takes over after hot
// standby (hsCoolRate is fitted on those plant runs, its start-up ramp included). A new stage change mid-blend starts a new
// blend from the slope shown at that moment, so the curve never jumps.
const BLEND_MIN=1;
const BEND_MED=(()=>{ const d=BENDS.borders.map(e=>e.sig.stack&&e.sig.stack.bend).filter(b=>b&&b[1]>b[0]).map(b=>b[1]-b[0]).sort((a,b)=>a-b); return d.length? d[d.length>>1]:11; })();
const borderD=(from,to)=>bendD(from,to,Math.round(BEND_MED/MJ_1090));
function blendRestart(s,r){
  if(s.rsAt==null) return r;
  const u=(s.t-s.rsAt)/s.rsD;
  if(u>=1){ s.rsAt=null; return r; }
  const m=mj(u); return s.rsFrom*(1-m)+r*m;
}
function applyRules(s){
  if(s.trip>0){ Object.assign(s,{air:6000,n2:1200,h2:60,ng:0,pox:0,I:0}); return; }
  if(s.fgAuto){ const want=s.T>T_FORMING && !ngOn(s); s.n2=want?1200:0; s.h2=want?60:0; }
  if(!ngOn(s)) s.I=0;
}
// Replay test on the 8 held-out plant stretches: mean error 56.4 → 17.5 °C; the plant-speed table used until now
// (data/bends.js "warm") gave 23.9 and is no longer needed. data/bends.js still feeds the bend panel.
function keep(s){
  if(!s.keeper||s.trip>0||!ngOn(s)||stage(s)==="Rated power"){ s.kept=false; return; }   // rated power: nothing by temperature
  if(s.T>KEEP){                                             // too hot: more air first, then a cooler air-in target
    if(!s.kept){ s.kept=true; s.keepAir=s.air; s.keepSp=s.target; }
    if(s.air<AIR_MAX) s.air=Math.min(AIR_MAX,s.air+KEEP_AIR);
    else if(heatOn(s)) s.target=Math.max(SP_MIN,s.target-KEEP_SP);
  } else if(s.kept && s.T<KEEP-KEEP_BAND){                  // cool enough: hand back, target first, then air
    if(s.target<s.keepSp) s.target=Math.min(s.keepSp,s.target+KEEP_SP/2);
    else if(s.air>s.keepAir) s.air=Math.max(s.keepAir,s.air-KEEP_AIR/2);
    else s.kept=false;
  }
}
function step(s){
  const h=1/60;
  keep(s);
  applyRules(s);
  followRec(s,h);
  followTin(s,h);
  if(!s.plantCool||!freeCooling(s)) s.coolAt=null;                       // plant cooling slope: only straight out of hot standby
  else if(s.coolAt==null && (s.lastSt==="Fuel switch"||s.lastSt==="Hot standby")) s.coolAt=s.t;
  const raw=s.coolAt!=null? hsCoolRate(s): rate(s), stNow=stage(s);
  if(stNow!==s.lastSt && s.rsAt!==s.t && s.coolAt!==s.t && Math.abs(raw-s.dT)>BLEND_MIN)
    Object.assign(s,{rsAt:s.t,rsFrom:s.dT,rsD:borderD(s.lastSt,stNow),rsBorder:`${s.lastSt}>${stNow}`});
  s.dT=blendRestart(s,raw); s.T+=s.dT*h; s.slope+=(s.dT-s.slope)*0.2; s.t+=1;
  // a restart into heat-up N₂+H₂ reads heat-up (not hot standby) until the stack really warms, or is back near hot standby
  if(s.reheat && (!heatOn(s)||ngOn(s)||s.slope>5||(s.T>=SP_HS-5&&s.dT>=0))) s.reheat=false;
  if(s.trip>0){ s.trip-=1; if(s.trip<=0){ s.air=6000; s.fgAuto=true; s.purgeDone=true; } }
  s.lastSt=stage(s);
}
function stage(s){
  if(s.feedSt) return s.feedSt;                     // data file: the row's stage
  if(s.trip>0) return "Trip: purge";
  if(loadOn(s)) return s.I>I_RATED_MIN? "Rated power":"Part load";
  if(ngOn(s)) return "Fuel switch";
  if(s.air<=AIR_COOL) return "Shutdown";
  if(!s.heaters) return "Air-flow cooling";
  if(fgOn(s)) return (s.slope>5||s.reheat)&&s.T<SP_HS? "Heat-up N₂+H₂":"Hot standby";   // heat-up only below hot standby
  return "Heat-up air";
}

// ---------- playbooks (flows = plant medians per stage) ----------
const F=n=>FLOWS[n]||{};
const PLAYS={
  cold:[
    {say:"Cold start (plant settings): air 6000 ln/min, heaters on, air heater 300 °C, outlet ramps 60 °C/h.", when:()=>true, act:s=>Object.assign(s,{air:F("Heat-up air").air,heaters:true,target:300,fgAuto:true,ng:0,pox:0,I:0})},
    {say:"Stack at 210 °C: N₂ + H₂ join, air heater up to 500 °C; the heat up ends when the stack settles near 505 °C.", when:s=>s.T>=T_FORMING, act:s=>{s.target=SP_HS;}},
    // the heat up always ends in hot standby: the minute the stack stops warming on N₂ + H₂ (old forming-gas plateau), the gas opens
    {say:`Heat up done → hot standby: natural gas ${F("Fuel switch")[14]} ln/min, POx air ${F("Fuel switch")[12]}, N₂ + H₂ close, air heater ${SP_FS} °C, no current (no power drawn). Part load only by its button.`, when:s=>stage(s)==="Hot standby", act:s=>toStandby(s)},
  ],
  down:[
    {say:`Shut down: NG and POx closed, current 0, heaters off, air ${SD_AIR} ln/min until the stack is below ${AIR_OFF_T} °C. N₂ + H₂ stay while above 210 °C.`, when:()=>true, act:s=>Object.assign(s,{ng:0,pox:0,I:0,heaters:false,air:SD_AIR,fgAuto:true})},
    {say:`Below ${AIR_OFF_T} °C: air off, plant in shutdown.`, when:s=>s.T<AIR_OFF_T, act:s=>{s.air=0;}},
  ],
  // after a trip purge (only from hot standby, part load or rated power): back to hot standby
  afterTrip:[
    {say:`Purge done: back to hot standby: air ${F("Fuel switch").air|0} ln/min, heaters on, air heater ${SP_FS} °C, natural gas ${F("Fuel switch")[14]} ln/min, no current.`, when:()=>true, act:s=>toStandby(s)},
  ],
};
// Hot-standby settings (plant fuel-switch medians: natural gas on, no current): end of heat up, after part load / rated power, after a trip purge.
function toStandby(s){
  const f=F("Fuel switch");
  Object.assign(s,{air:f.air,ng:f[14],pox:f[12],I:0,heaters:true,target:SP_FS,fgAuto:true,kept:false});
  applyRules(s);
}
// Part load / rated power settings (n = stage key); only from the buttons (stage bar or Go to …).
function toLoad(s,n){ const f=F(n); Object.assign(s,{air:f.air,ng:f[14],pox:f[12],I:f.I,heaters:true,target:SP_PL,kept:false}); }
const loadMsg=n=>`${nm(n)}: air ${F(n).air|0}, NG ${F(n)[14]|0}, POx ${F(n)[12]|0} ln/min, ${F(n).I} A per string, air heater ${SP_PL} °C.`
  +(n==="Rated power"?" Holds until a button is pressed (then hot standby); nothing changes by temperature (no keeper, no automatic trip). No plant data at this power (52 kW): readings are rated values extrapolated from part load (best-fitting curve per sensor), string voltage from the current, stack from the heat balance.":"");
let play=null, playStep=0, playMsg="";
function startPlay(n){ play=PLAYS[n]; playStep=0; runPlay(); }
function runPlay(){ if(!play) return; while(playStep<play.length && play[playStep].when(S)){ play[playStep].act(S); playMsg=play[playStep].say; playStep++; } if(playStep>=play.length) play=null; }
function manual(){ play=null; S.estop=false; playMsg="Manual control."; }
// Part load and rated power are always followed by hot standby (or each other, or a trip purge): if the twin leaves them any
// other way (Shut down, natural gas off, heaters or air changed), it unloads to hot-standby settings instead. Current to 0
// with the gas on is hot standby itself. An emergency stop overrides all of this.
function followPartLoad(s){
  if(s.estop){ s.plWas=false; return; }
  const st=stage(s);
  if(s.plWas && !LOADS.includes(st) && st!=="Fuel switch" && st!=="Trip: purge"){
    play=null; toStandby(s);
    playMsg=`${nm(s.plWas)} is always followed by hot standby (not ${lc(nm(st))}): current 0, natural gas ${Math.round(s.ng)} ln/min stays on, air ${Math.round(s.air)} ln/min, heaters on, air heater ${SP_FS} °C. Shut down works from hot standby.`;
  }
  s.plWas=LOADS.includes(stage(s))&&stage(s);
}
function tick(n){ for(let i=0;i<n;i++){ step(S); runPlay(); if(S.purgeDone){ S.purgeDone=false; startPlay("afterTrip"); } followPartLoad(S); S.hist.push({t:S.t,T:S.T,st:stage(S)}); noteBorder(S); followSensors(S); S.hist[S.hist.length-1].v=recordAll(); checkTrip(S); } if(S.hist.length>2880) S.hist.splice(0,S.hist.length-2880); }
// Trip purge: only from hot standby, part load or rated power.
const canPurge=s=>s.trip<=0&&!s.estop&&PURGE_FROM.includes(stage(s));
const lc=t=>t[0].toLowerCase()+t.slice(1);
const noPurgeMsg=s=>s.estop?"Trip / emergency purge is locked after an emergency stop.":`Trip / emergency purge is allowed only from hot standby, part load or rated power, not from ${lc(nm(stage(s)))}.`;
function startPurge(s,msg){
  if(!canPurge(s)) return false;
  play=null; s.noPurgeWarn=false; Object.assign(s,{trip:PURGE_MIN,heaters:false}); applyRules(s); playMsg=msg;
  return true;
}
// Stack safety thermocouple TIRZ 8.1.3 at 720 °C: the twin only warns, it changes nothing by temperature (user, 2026-11-06:
// the physics behind the data stays intact). Trip / emergency purge by button only.
function checkTrip(s){
  const z=val(STACK_SAFETY);
  if(s.trip>0||s.estop||z==null) return;
  if(z<STACK_TRIP){ s.noPurgeWarn=false; return; }
  if(!s.noPurgeWarn){ s.noPurgeWarn=true; playMsg=`Stack safety ${Math.round(z)} °C is above the ${STACK_TRIP} °C trip. No automatic purge: the twin changes nothing by temperature; Trip / emergency purge by button.`; }
}
function noteBorder(s){ const h=s.hist, n=h.length; if(n>1 && h[n-1].st!==h[n-2].st) s.border={t:h[n-1].t,from:h[n-2].st,to:h[n-1].st,jump:s.jumpAt!=null&&s.t-s.jumpAt<=1}; }

// ---------- stage-border bend & jerk (same method as 03_data_analysis/scripts/slopes_jerk.py) ----------
// slope = 30-min line fit each side (°C/h); bend time = 9-min smoothed slope going 10 → 90 % of the change;
// peak acceleration (°C/h per min) and jerk (°C/h per min²) within ±15 min, slope from a 5-min median then 5-min mean (border_shape).
const BW=30, B_PRE=45, B_POST=60;
const lineSlope=(xs,ys)=>{ const n=xs.length, mx=xs.reduce((a,b)=>a+b,0)/n, my=ys.reduce((a,b)=>a+b,0)/n; let sxy=0,sxx=0; for(let i=0;i<n;i++){ sxy+=(xs[i]-mx)*(ys[i]-my); sxx+=(xs[i]-mx)**2; } return sxy/sxx*60; };
const smooth=(v,w)=>v.map((_,i)=>{ let s=0,c=0; for(let j=i-(w>>1);j<=i+(w>>1);j++) if(j>=0&&j<v.length&&isFinite(v[j])){ s+=v[j]; c++; } return c>=3?s/c:NaN; });
const smed=(v,w)=>v.map((_,i)=>{ const a=v.slice(Math.max(0,i-(w>>1)),i+(w>>1)+1).filter(isFinite).sort((p,q)=>p-q), n=a.length; return n<3?NaN:n%2?a[n>>1]:(a[n/2-1]+a[n/2])/2; });
const grad=v=>v.map((_,i)=>i===0?v[1]-v[0]:i===v.length-1?v[i]-v[i-1]:(v[i+1]-v[i-1])/2);
function twinBend(b){
  if(!b) return null;
  const from=Math.max(b.t-(b.jump?0:B_PRE), S.jumpAt!=null&&S.jumpAt<b.t? S.jumpAt+1:-Infinity);   // never reach back across a stage-bar jump
  const pts=S.hist.filter(p=>p.t>=from&&p.t<=b.t+B_POST), z=pts.find(p=>p.t===b.t);
  if(!z) return null;
  const tm=pts.map(p=>p.t-b.t), y=pts.map(p=>p.T-z.T), after=tm[tm.length-1]+1;
  const sel=(a,c)=>tm.map((t,i)=>t>=a&&t<c?i:-1).filter(i=>i>=0);
  const pi=sel(-BW,0), qi=sel(0,BW);
  const pre=!b.jump&&pi.length===BW? lineSlope(pi.map(i=>tm[i]),pi.map(i=>y[i])):null;
  const post=qi.length>=5? lineSlope(qi.map(i=>tm[i]),qi.map(i=>y[i])):null;
  const r={tm,y,pre,post,after,bend:null,acc:null,jerk:null};
  if(after>=20 && pi.length>=15){
    const v=grad(smooth(y,9)).map(x=>x*60), vs=grad(smooth(smed(y,5),5)).map(x=>x*60), acc=grad(smooth(vs,5)), jrk=grad(smooth(acc,5));
    const core=tm.map((t,i)=>t>=-15&&t<15?i:-1).filter(i=>i>=0), mx=a=>Math.max(...core.map(i=>Math.abs(a[i])).filter(isFinite));
    r.acc=mx(acc); r.jerk=mx(jrk);
    if(pre!=null && post!=null && after>=BW+10 && Math.abs(post-pre)>5){
      const zone=tm.map((t,i)=>t>=-20&&t<=40?i:-1).filter(i=>i>=0), f=i=>(v[i]-pre)/(post-pre);
      const i10=zone.find(i=>f(i)>=0.1), i90=zone.find(i=>f(i)>=0.9);
      if(i90!=null) r.bend=[tm[i10],tm[i90]];
    }
  }
  return r;
}
const plantBend=b=>b&&BENDS.borders.find(e=>e.from===b.from&&e.to===b.to);

// ---------- schematic ----------
const NS="http://www.w3.org/2000/svg";
const airOn=s=>s.air>AIR_COOL, anyFuel=s=>fgOn(s)||ngOn(s)||s.n2>N2_ON||s.h2>H2_ON;
const PIPES=[ // id, path, fluid colour, part it belongs to, on()
  ["air1","M92 190H420","--air","air",airOn],
  ["air2","M150 190V240H420V190","--air","air",airOn],
  ["airM","M420 190H490","--air","air",airOn],
  ["twvE","M510 190H600","--air","twv",airOn],
  ["eaphS","M680 190H770","--air","eaph",airOn],
  // APH1 and APH2 run in PARALLEL (as on the P&ID): air enters each from the TWV leg,
  // both air outlets join in the riser to the EAPH; each gets its own flue stream from the burner.
  ["twvA","M500 200V415H540","--air","twv",airOn],
  ["twvA1","M500 275H540","--air","twv",airOn],
  ["riser","M600 415H620V212","--air","aph2",airOn],
  ["riser1","M600 275H620","--air","aph1",airOn],
  ["pox","M92 310H520V545H680V460H700","--pox","pox",s=>s.pox>20],
  ["h2","M92 400H470","--h2","h2",s=>s.h2>H2_ON],
  ["n2","M92 450H470","--n2","n2",s=>s.n2>N2_ON],
  ["purge","M470 400V600","--n2","n2",s=>s.h2>H2_ON||s.n2>N2_ON],
  ["ng","M92 600H720","--ng","ng",ngOn],
  ["ejR","M740 585V500","--fuel","ejector",anyFuel],
  ["refE","M740 380V335","--fuel","reformer",anyFuel],
  ["eaghS","M740 305V235H770","--fuel","eagh",anyFuel],
  ["anOut","M1070 235H1120V600H1050","--fuel","stack",anyFuel],
  ["rec","M990 600H760","--fuel","eaoh3",ngOn],
  ["ao1","M1120 450H1050","--fuel","eaoh1",anyFuel],
  ["ao1t","M990 450H900","--fuel","eaoh1",anyFuel],
  ["ao2","M1120 520H1050","--fuel","eaoh2",anyFuel],
  ["ao2t","M990 520H940V470H900","--fuel","eaoh2",anyFuel],
  ["cath","M1070 175H1160V400H900","--air","tox",airOn],
  ["flue","M850 380V350H690V242H585V250","--flue","tox",s=>airOn(s)||anyFuel(s)],   // TOX outlet 1 (TIR 7.1.1) → APH1
  ["flue2","M690 350H640V462H585V440","--flue","tox",s=>airOn(s)||anyFuel(s)],      // TOX outlet 2 (TIR 7.1.2) → APH2
  ["flueO1","M570 300V345","--flue","aph1",s=>airOn(s)||anyFuel(s)],                // APH1 flue out (TIR 7.3.1)
  ["flueO2","M570 390V345","--flue","aph2",s=>airOn(s)||anyFuel(s)],                // APH2 flue out (TIR 7.3.2)
  ["exh","M570 345H472","--flue","exhaust",s=>airOn(s)||anyFuel(s)],                // joined → exhaust (TIR 7.04)
];
for(let i=0;i<5;i++){ const x=807+i*57; PIPES.push([`el${i}`,`M${x} 175V111`,"--elec","dcdc",loadOn],[`bus${i}`,`M${x} 40V24`,"--elec","load",loadOn]); }
PIPES.push(["bus","M807 24H1085","--elec","load",loadOn]);   // DC/DC outputs join on one bus to the load bank

const PARTS={
  air:{title:"Cathode air supply",desc:"Two mass flow controllers (MFC-Air-1, -2) feed the cathode air; the streams merge before the three way valve."},
  twv:{title:"three way valve TWV-CA",desc:"Splits the cathode air between the recuperators (APH) and the direct path to the electric air heater. Driven by temperature, not a knob."},
  pox:{title:"POx air",desc:"Partial oxidation air to the reformer. On with natural gas (hot standby, part load, rated power)."},
  n2:{title:"Nitrogen (forming gas)",desc:"N₂ for forming gas and purge. Rule: on above 210 °C while no natural gas."},
  h2:{title:"Hydrogen (forming gas)",desc:"H₂ part of the forming gas that keeps the anode reduced."},
  ng:{title:"Natural gas line",desc:"Desulphuriser, booster compressor, 15 bar storage, then MFC-Fuel FIRC 1.4 to the ejector."},
  aph1:{title:"Air preheater APH-1",desc:"Recuperator, in parallel with APH-2: cathode air picks up heat from its own flue gas stream (burner outlet 1, TIR 7.1.1)."},
  aph2:{title:"Air preheater APH-2",desc:"Recuperator, in parallel with APH-1, fed by burner outlet 2 (TIR 7.1.2). Both air outlets join in the riser to the electric air heater; both flue outlets join and go to the exhaust."},
  eaph:{title:"Electric air heater EAPH",desc:"40 kW electric heater; its outlet TIRC 2.06 is the stack cathode inlet temperature."},
  ejector:{title:"Ejector",desc:"Natural gas drives the ejector and pulls anode off gas back through EAOH3 (recycle)."},
  reformer:{title:"Reformer",desc:"Converts natural gas (with recycle and POx air) to H₂ + CO for the anode."},
  erh:{title:"Reformer housing heater ERH",desc:"3.3 kW heater on the reformer/burner housing. Safety trip 860 °C."},
  eagh:{title:"Anode gas heater EAGH",desc:"1.3 kW line heater between reformer outlet and stack anode inlet."},
  stack:{title:"SOFC stack module",desc:"5 strings × 4 stacks. Stack temperature is the twin's model value; other readings follow the plant data. String current and voltage (EIRC 4.x) and the stack voltage per module (Σ stacks M1–M5) are listed at the end."},
  dcdc:{title:"DC/DC converters (per string)",desc:"One converter per string (14 kW, 600 V, 42 A each): current, voltage and stack voltage of each string as logged by the plant."},
  load:{title:"Load bank (total)",desc:"Combined output of the five strings. All three are twin calculated sensors (no plant tag): Σ P = Σ V × I, Σ I = sum of string currents, V = Σ P ÷ Σ I (current weighted string voltage; mean string voltage when no current flows)."},
  eaoh3:{title:"Off gas heater EAOH3 (recycle)",desc:"Heats the anode off gas that returns to the ejector."},
  eaoh1:{title:"Off gas heater EAOH1",desc:"Anode off gas branch 1 to the burner."},
  eaoh2:{title:"Off gas heater EAOH2",desc:"Anode off gas branch 2 to the burner."},
  tox:{title:"Afterburner (TOX)",desc:"Burns anode off gas with the cathode off gas; the hot flue gas leaves through two outlets, one to each APH."},
  exhaust:{title:"Exhaust",desc:"The two APH flue gas outlets join and leave through the roof exhaust. Safety trip 300 °C."},
};
const HEATERS=new Set(["eaph","erh","eagh","eaoh1","eaoh2","eaoh3"]);

function el(tag,attrs,parent,text){ const e=document.createElementNS(NS,tag); for(const k in attrs) e.setAttribute(k,attrs[k]); if(text!=null) e.textContent=text; if(parent) parent.appendChild(e); return e; }
const gp=document.getElementById("pipes"), gparts=document.getElementById("parts");
const flowEls={};
PIPES.forEach(([id,d])=>el("path",{class:"pipe",d},gp));
PIPES.forEach(([id,d,c])=>{ flowEls[id]=el("path",{class:"flow",d,stroke:`var(${c})`},gp); });
const hitEls={};
PIPES.forEach(([id,d,c,part])=>{ const h=el("path",{class:"hit",d,"data-part":part},gp); hitEls[id]=h; h.addEventListener("click",()=>select(part,id)); });

const partEls={}, live={};
function part(id,label,build){
  const g=el("g",{class:"part","data-part":id,tabindex:"0",role:"button","aria-label":`${PARTS[id].title}: show sensors`},gparts);
  build(g); partEls[id]=g;
  g.addEventListener("click",()=>select(id));
  g.addEventListener("keydown",e=>{ if(e.key==="Enter"||e.key===" "){ e.preventDefault(); select(id); } });
}
const box=(g,x,y,w,h)=>el("rect",{class:"sh",x,y,width:w,height:h,rx:4},g);
const coil=(g,x,y,w)=>{ let d=`M${x} ${y}`; for(let i=0;i<6;i++) d+=` l${w/12} -6 l${w/12} 6`; el("path",{class:"coil",d},g); };
const mfc=(g,cx,cy,tag)=>{ el("circle",{class:"sh",cx,cy,r:17},g); el("text",{x:cx,y:cy-2,"text-anchor":"middle","font-size":"9"},g,"FIRC"); el("text",{x:cx,y:cy+9,"text-anchor":"middle","font-size":"9"},g,tag); };
const src=(g,x,y,label)=>{ el("path",{class:"src",d:`M14 ${y-11}H80L92 ${y}L80 ${y+11}H14Z`},g); el("text",{x:20,y:y+4,"font-size":"11"},g,label); };

part("air","",g=>{ src(g,0,190,"Cathode air"); mfc(g,260,190,"1.1.1"); mfc(g,260,240,"1.1.2");
  live.air=el("text",{x:300,y:180,class:"v"},g,""); });
part("twv","",g=>{ el("path",{class:"sh",d:"M488 180L500 190L488 200ZM512 180L500 190L512 200ZM490 212L500 190L510 212Z"},g); el("text",{x:500,y:172,"text-anchor":"middle",class:"m"},g,"TWV"); });
part("pox","",g=>{ src(g,0,310,"POx air"); mfc(g,260,310,"1.2"); live.pox=el("text",{x:282,y:300,class:"v"},g,""); });
part("h2","",g=>{ src(g,0,400,"Hydrogen"); mfc(g,260,400,"1.5"); live.h2=el("text",{x:282,y:390,class:"v"},g,""); });
part("n2","",g=>{ src(g,0,450,"Nitrogen"); mfc(g,260,450,"1.3"); live.n2=el("text",{x:282,y:440,class:"v"},g,""); });
part("ng","",g=>{ src(g,0,600,"Natural gas");
  box(g,108,586,44,28); el("text",{x:130,y:604,"text-anchor":"middle","font-size":"10"},g,"Desulf");
  el("circle",{class:"sh",cx:190,cy:600,r:15},g); el("path",{class:"coil",d:"M181 594L199 600L181 606"},g); el("text",{x:190,y:630,"text-anchor":"middle",class:"m"},g,"Compressor");
  box(g,228,580,30,40); el("text",{x:243,y:635,"text-anchor":"middle",class:"m"},g,"15 bar");
  mfc(g,340,600,"1.4"); live.ng=el("text",{x:362,y:590,class:"v"},g,""); });
part("aph1","",g=>{ box(g,540,250,60,50); el("circle",{cx:570,cy:275,r:13,class:"coil"},g); el("path",{class:"coil",d:"M560 282l6-14l8 14l6-14"},g); el("text",{x:540,y:244,class:"t"},g,"APH1"); });
part("aph2","",g=>{ box(g,540,390,60,50); el("circle",{cx:570,cy:415,r:13,class:"coil"},g); el("path",{class:"coil",d:"M560 422l6-14l8 14l6-14"},g); el("text",{x:540,y:458,class:"t"},g,"APH2"); });
part("eaph","",g=>{ box(g,600,168,80,44); coil(g,612,196,56); el("text",{x:640,y:162,"text-anchor":"middle",class:"t"},g,"EAPH"); live.eaph=el("text",{x:640,y:228,"text-anchor":"middle",class:"v"},g,""); });
part("ejector","",g=>{ el("path",{class:"sh",d:"M720 588L760 594V606L720 612Z"},g); el("text",{x:740,y:632,"text-anchor":"middle",class:"m"},g,"Ejector"); });
part("reformer","",g=>{ box(g,700,380,80,120); el("path",{class:"coil",d:"M708 395L772 485M708 425L752 485M728 395L772 455M748 395L772 425"},g); el("text",{x:740,y:515,"text-anchor":"end",class:"t",transform:"translate(-44 0)"},g,"Reformer"); });
part("erh","",g=>{ box(g,650,385,42,40); coil(g,655,410,32); el("text",{x:671,y:378,"text-anchor":"middle",class:"t"},g,"ERH"); live.erh=el("text",{x:671,y:440,"text-anchor":"middle",class:"v"},g,""); });
part("eagh","",g=>{ box(g,708,305,64,30); coil(g,714,325,52); el("text",{x:780,y:318,class:"t"},g,"EAGH"); live.eagh=el("text",{x:780,y:332,class:"v"},g,""); });
part("tox","",g=>{ box(g,800,380,100,120); el("path",{class:"coil",d:"M836 470q14-30 0-56q30 26 0 56z"},g); el("text",{x:850,y:398,"text-anchor":"middle",class:"t"},g,"Burner (TOX)"); live.tox=el("text",{x:850,y:492,"text-anchor":"middle",class:"v"},g,""); });
part("eaoh1","",g=>{ box(g,990,435,60,30); coil(g,996,455,48); el("text",{x:1020,y:428,"text-anchor":"middle",class:"t"},g,"EAOH1"); });
part("eaoh2","",g=>{ box(g,990,505,60,30); coil(g,996,525,48); el("text",{x:1020,y:498,"text-anchor":"middle",class:"t"},g,"EAOH2"); });
part("eaoh3","",g=>{ box(g,990,585,60,30); coil(g,996,605,48); el("text",{x:1020,y:578,"text-anchor":"middle",class:"t"},g,"EAOH3"); live.eaoh=el("text",{x:1020,y:632,"text-anchor":"middle",class:"v"},g,""); });
part("exhaust","",g=>{ el("path",{class:"src",d:"M472 335L454 345L472 355Z"},g); el("text",{x:456,y:370,class:"m"},g,"Exhaust"); el("text",{x:456,y:382,class:"m"},g,"(roof)"); });
part("stack","",g=>{ el("rect",{class:"sh",x:770,y:150,width:300,height:110,rx:6,id:"stackShape"},g);
  for(let i=0;i<5;i++){ const x=785+i*57; el("rect",{x,y:175,width:45,height:62,rx:2,fill:"none",stroke:"rgba(255,255,255,.55)","stroke-width":1},g);
    for(let j=1;j<6;j++) el("path",{d:`M${x+4} ${175+j*10.3}H${x+41}`,stroke:"rgba(255,255,255,.35)"},g); }
  el("text",{x:920,y:168,"text-anchor":"middle",style:"fill:#fff;font-size:12px;font-weight:500"},g,"SOFC stack module");
  live.stack=el("text",{x:920,y:254,"text-anchor":"middle",style:"fill:#fff;font-family:var(--f-mono);font-size:13px"},g,"");
  el("text",{x:765,y:186,"text-anchor":"end",class:"m"},g,"cathode in"); el("text",{x:765,y:232,"text-anchor":"end",class:"m"},g,"anode in");
  el("text",{x:1076,y:168,class:"m"},g,"cathode out"); el("text",{x:1076,y:252,class:"m"},g,"anode out"); });
// DC/DC converters: one box per string (4.1–4.5) with current, voltage and P = V × I.
part("dcdc","",g=>{ el("text",{x:772,y:72,"text-anchor":"end",class:"t"},g,"DC/DC"); el("text",{x:772,y:86,"text-anchor":"end",class:"m"},g,"per string"); live.dcdc=[];
  for(let i=0;i<5;i++){ const x=780.5+i*57, cx=x+26.5; box(g,x,40,53,71); el("text",{x:cx,y:53,"text-anchor":"middle","font-size":"10","font-weight":"600"},g,`4.${i+1}`);
    live.dcdc.push([64,76,88,100].map(y=>el("text",{x:cx,y,"text-anchor":"middle",class:"v","font-size":"9.5"},g,""))); } });
// Load bank: the combined output on the bus (calculated sensors Σ P, Σ I, V).
part("load","",g=>{ box(g,1085,13,100,98); el("text",{x:1135,y:30,"text-anchor":"middle","font-size":"10","font-weight":"600"},g,"Load bank");
  live.load=[48,66,84,102].map(y=>el("text",{x:1135,y,"text-anchor":"middle",class:"v"},g,"")); });

document.getElementById("fluidLegend").innerHTML=[["--air","Cathode air"],["--pox","POx air"],["--h2","H₂"],["--n2","N₂"],["--ng","Natural gas"],["--fuel","Fuel / off gas"],["--flue","Flue gas"],["--elec","Power"],["--heat","Heater on"]]
  .map(([c,n])=>`<span><i style="background:var(${c})"></i>${n}</span>`).join("");

// ---------- sensor readings ----------
const KNOB={"ct_FIRC_111_PV_ProcessValue":s=>s.air/2,"ct_FIRC_112_PV_ProcessValue":s=>s.air/2,"ct_FIRC_12_PV_ProcessValue":s=>s.pox,
  "ct_FIRC_13_PV_ProcessValue":s=>s.n2,"ct_FIRC_14_PV_ProcessValue":s=>s.ng,"ct_FIRC_15_PV_ProcessValue":s=>s.h2,"T_stack_C":s=>s.T};
// EAPH box: model values (A outlet = air-in, D inlet = recuperator air, B power from the air heat), not the per-stage table
const STR=[1,2,3,4,5].map(n=>[`PLC_hostSetp_ctrl_ctEIRC4${n}_rCurrMonitor`,`PLC_hostSetp_ctrl_ctEIRC4${n}_rVoltMonitor`]);
// Gross DC efficiency (03_data_analysis/scripts/efficiency_check.py): DC power ÷ gas energy. FIRC 1,4 is logged as pure CH4
// (PLC_pv_rM_CH4 = 0.042943 kg/h per ln/min), LHV 50 MJ/kg. No gas while heating up → no value.
// shortcut: one gas meter only, so a string gets 1/5 of the gas (as the PLC rFU_Worst tags): ranks strings, not a measured split.
const FUEL_KW=0.042943/3600*50000, eta=(P,ng,share=1)=>ng>1? P/(ng*FUEL_KW/share)*100: null;
const sumI=()=>STR.reduce((a,[i])=>a+(val(i)??0),0), sumP=()=>STR.reduce((a,[i,u])=>a+(val(i)??0)*(val(u)??0),0);
const CALC={"TIRC_2_06":s=>s.Tin,"TIR_2_05":eaphIn,"EIRC_2_01_ActV_In_ThreePhasePower":eaphPower,
  P_total_kW:()=>sumP()/1000, I_total_A:sumI,
  // shortcut: no bus voltage is logged, so V is the current-weighted string voltage (keeps Σ P = V × Σ I); use the real bus voltage if one is found
  V_total_V:()=>{ const I=sumI(); return I>0? sumP()/I: STR.reduce((a,[,u])=>a+(val(u)??0),0)/5; },
  eta_module_pct:()=>eta(sumP()/1000,val("ct_FIRC_14_PV_ProcessValue"))};
STR.forEach(([i,u],k)=>CALC[`eta_string${k+1}_pct`]=()=>eta((val(i)??0)*(val(u)??0)/1000,val("ct_FIRC_14_PV_ProcessValue"),5));
// Per-string rows (plant tags) → DC/DC part; the load bank keeps only the three twin-made totals (no plant tag, no plant range).
DATA.components.dcdc=[...DATA.components.load,...[1,2,3,4,5].map(k=>({tag:`η 4.${k}`,col:`eta_string${k}_pct`,
  desc:`String 4.${k} gross DC efficiency (V × I ÷ ⅕ of the gas energy; equal gas split assumed, one gas meter)`,unit:"%",fits:{}}))];
DATA.components.load=[{tag:"Σ P",col:"P_total_kW",desc:"Load bank total power (Σ V × I, 5 strings)",unit:"kW",fits:{}},
  {tag:"Σ I",col:"I_total_A",desc:"Load bank total current (sum of the 5 string currents)",unit:"A",fits:{}},
  {tag:"V",col:"V_total_V",desc:"Load bank voltage (Σ P ÷ Σ I; mean string voltage at 0 A)",unit:"V",fits:{}},
  {tag:"η",col:"eta_module_pct",desc:"Module gross DC efficiency (Σ P ÷ gas energy, FIRC 1.4 as CH4, LHV 50 MJ/kg; blower and heaters not subtracted)",unit:"%",fits:{}}];
Object.assign(KNOB,CALC);
for(let i=1;i<=5;i++) KNOB[`PLC_hostSetp_ctrl_ctEIRC4${i}_rCurrMonitor`]=s=>loadOn(s)?s.I:0;
const TRIP={"TIRZ_8_1_1":1050,"TIRZ_8_1_3":720,"TIRZ_8_1_9":930,"TIRZ_8_1_10":300,"TIRZ_8_2_1":950,"TIRZ_8_2_2":950,"TIRZ_8_2_3":950,"TIRZ_8_2_4":950,"TIRZ_8_2_5":860};
// "Near trip": a reading within NEAR K of its trip (or above it) → bold in the list, its block on the drawing blinks.
const NEAR=40, nearTrip=(col,v)=>TRIP[col]!=null&&v!=null&&v>TRIP[col]-NEAR;
// Rated power has no plant data (v3.2): every look-up sensor shows its rated value from the part-load extrapolation
// (r.rated at 30 A = 52 kW, best-fitting curve per sensor: 03_data_analysis/rated_power_extrapolation.ipynb §4.7). The string
// voltages follow the current (V = V0 + b·I per string, string_vi_fit.csv: 52.0 kW at 30 A). Knob, model and CALC sensors stay
// twin-made, and the stack safety TC keeps following the twin stack (heat balance), not the extrapolated 764 °C.
// The plant band shown under each reading stays the part-load one, so the rated value is seen against what the plant did.
// shortcut: one fixed value per sensor (rated power is always 30 A); interpolate use_<p>kW by power if rated power ever varies.
Object.values(DATA.components).flat().forEach(r=>{ if(r.fits["Part load"]) r.fits["Rated power"]=r.fits["Part load"]; });
const VI={}; [[486.66,-4.662],[492.27,-4.866],[482.52,-5.476],[477.36,-3.809],[501.16,-4.746]].forEach(([v0,b],k)=>VI[STR[k][1]]=I=>v0+b*I);
function reading(r,st){
  if(st==="Rated power" && VI[r.col]) return {v:VI[r.col](S.I),f:r.fits[st]};
  const f=r.fits[st];
  if(KNOB[r.col]) return {v:KNOB[r.col](S),f,knob:true};
  if(st==="Rated power" && r.rated && r.col!==STACK_SAFETY) return {v:r.rated.v,f,rated:true};
  if(!f) return {v:null,f:null};
  const [a,b,p2,,,,p98]=f, hi=r.col===STACK_SAFETY?Infinity:p98;   // the safety TC follows the twin stack past the plant's hottest reading
  return {v:Math.min(hi,Math.max(p2,a+b*S.T)),f};
}
const byCol={}; Object.values(DATA.components).flat().forEach(r=>byCol[r.col]=r);

// ---------- stage-change jerk for sensor readings (data/sensors.js "ease", tools/prep.py) ----------
// At a stage change the per-stage fit switches. Slow sensors (temperatures, heater current/power, 3-way valve)
// blend from the old-stage to the new-stage reading on a minimum-jerk S-curve (speed and acceleration zero at
// both ends) with the plant's own delay and duration for that sensor and border type. Only the 4 border types
// where >= 3 sensors moved clearly on the plant; flows and pressures step, like the plant's valves.
// Held-out test on the 39 days: error 19.9 -> 13.3 % of the move (median), better in 65 % of cases.
// All other stage changes (2026-11-04, user: no sharp transitions): the per-stage tables switch there too, so without a
// blend a reading could step tens to hundreds of °C in one minute (air-flow cooling → shutdown: 27 temperatures up to 38 °C;
// part load → hot standby: up to 551 °C; trip purge in/out ~190 °C). The plant has no clean timing for those border types,
// so each slow sensor uses its own median plant duration over the 4 timed border types (no delay); flows/pressures still step.
const ROWS=Object.values(DATA.components).flat().filter(r=>!KNOB[r.col]);
const med=a=>{ const b=[...a].sort((x,y)=>x-y), n=b.length; return n? (n%2? b[n>>1]: (b[n/2-1]+b[n/2])/2): null; };
ROWS.forEach(r=>{ const D=r.ease? med(Object.values(r.ease).map(k=>k[1])): null; if(D) r.easeDef=[0,Math.round(D*10)/10]; });
const EASE={}, SHOWN={};
let jerkOn=true;
function eased(r,now){
  const e=EASE[r.col];
  if(!e||now==null) return now;
  const s=mj((S.t-e.t0-e.d)/e.D);
  if(s>=1){ delete EASE[r.col]; return now; }
  const old=(e.from?reading(r,e.from).v??0:0)+e.c;   // old-stage line at today's stack T (+ offset if a blend was running)
  return old*(1-s)+now*s;
}
function followSensors(s){
  const h=s.hist, n=h.length, st=h[n-1].st, prev=n>1?h[n-2].st:st, jumped=s.jumpAt!=null&&s.t-s.jumpAt<=1;
  for(const r of ROWS){
    const now=reading(r,st).v;
    if(st!==prev){
      const plant=r.ease&&r.ease[prev+">"+st], k=jerkOn&&!jumped&&(plant||r.easeDef), last=SHOWN[r.col];
      if(k&&now!=null&&last!=null){ const old=reading(r,prev).v; EASE[r.col]={from:old==null?null:prev,c:last-(old??0),t0:s.t,d:k[0],D:k[1],pst:prev,def:!plant}; }
      else delete EASE[r.col];
    }
    SHOWN[r.col]=eased(r,now);
  }
}
function snapSensors(){ const st=stage(S); for(const k in EASE) delete EASE[k]; for(const r of ROWS) SHOWN[r.col]=reading(r,st).v; }
// readings shown = the eased value from the last simulated minute (time has to run for a reading to move)
// Data viewer (source Data file, below): FEED.row = the shown minute's values, indexed like S.hist[i].v.
const FEED={mode:"twin",rows:[],i:0,row:null,lastT:-Infinity};
function shown(r,st){ if(FEED.row){ const x=FEED.row[IDX.get(r.col)]; return {v:x===x?x:null,f:r.fits[st]}; }
  const x=reading(r,st); if(!x.knob && r.col in SHOWN){ x.v=SHOWN[r.col]; x.ease=EASE[r.col]; } return x; }
const val=(col)=>{ const r=byCol[col]; return r? shown(r,stage(S)).v:null; };
const fmt=(v,u)=>v==null?"–":(u==="°C"||u==="ln/min"||u==="V"? Math.round(v).toString(): Math.abs(v)>=100? v.toFixed(0): Math.abs(v)>=10? v.toFixed(1): v.toFixed(2));

// ---------- sensor history (every reading the twin shows, once per simulated minute) ----------
// ALLROWS = every sensor row of every part (knob flows, model values and plant look-ups alike).
// S.hist[i].v = Float32Array of the shown values at that minute (NaN = no reading), so any sensor can be plotted.
const ALLROWS=Object.values(DATA.components).flat(), IDX=new Map();
ALLROWS.forEach((r,i)=>{ if(!IDX.has(r.col)) IDX.set(r.col,i); });
function recordAll(){ const st=stage(S), a=new Float32Array(ALLROWS.length); ALLROWS.forEach((r,i)=>{ const v=shown(r,st).v; a[i]=v==null||!isFinite(v)?NaN:v; }); return a; }

// ---------- groups: the three zones of the drawing, plus everything ----------
// A click on a zone background (or a chip above the list) shows every sensor of that zone, part by part.
const GROUPS={
  fpm:{chip:"Supply (FPM)",title:"FPM · supply (group)",desc:"All sensors of the supply zone: cathode air, POx air, hydrogen, nitrogen and natural gas lines.",parts:["air","pox","h2","n2","ng"]},
  pgm:{chip:"Process module (PGM)",title:"PGM · process module (group)",desc:"All sensors of the process module: three way valve, recuperators, air heater, fuel path, stack, off gas heaters, burner and exhaust.",parts:["twv","aph1","aph2","eaph","ejector","reformer","erh","eagh","stack","eaoh3","eaoh1","eaoh2","tox","exhaust"]},
  loads:{chip:"Electrical loads",title:"Electrical loads (group)",desc:"All electrical sensors: current and voltages per string at the DC/DC converters, then the load bank totals.",parts:["dcdc","load"]},
  all:{chip:"All sensors",title:"All sensors in the twin",desc:"Every sensor the twin shows, part by part.",parts:Object.keys(DATA.components).filter(k=>PARTS[k])},
};
const isGroup=id=>id.startsWith("g:");
const gChips=document.getElementById("gChips"), pRowsEl=document.getElementById("pRows"), readEl=pRowsEl.closest(".read");
gChips.innerHTML=Object.entries(GROUPS).map(([k,g])=>`<button type="button" data-g="${k}">${g.chip}</button>`).join("");
gChips.querySelectorAll("button").forEach(b=>b.addEventListener("click",()=>select("g:"+b.dataset.g)));
document.querySelectorAll("#pid .zone").forEach(z=>{ const g=GROUPS[z.dataset.group];
  z.setAttribute("tabindex","0"); z.setAttribute("role","button"); z.setAttribute("aria-label",`${g.title}: show all sensors`);
  z.addEventListener("click",()=>select("g:"+z.dataset.group));
  z.addEventListener("keydown",e=>{ if(e.key==="Enter"||e.key===" "){ e.preventDefault(); select("g:"+z.dataset.group); } }); });

let selected="stack", selPipe=null, rowEls=[];
const openPlot=new Set();
function selRows(){
  const parts=isGroup(selected)? GROUPS[selected.slice(2)].parts: [selected], seen=new Set(), out=[];
  parts.forEach(p=>(DATA.components[p]||[]).forEach(r=>{ if(!seen.has(r.col)){ seen.add(r.col); out.push({r,part:p}); } }));
  // stack panel also lists the string current/voltage rows of the DC/DC part (same rows, not copies, so history/CSV stay single)
  if(selected==="stack") DATA.components.dcdc.forEach(r=>{ if(!seen.has(r.col)){ seen.add(r.col); out.push({r,part:"dcdc"}); } });
  return out;
}
function select(id,pipe){
  selected=id; selPipe=pipe||null;
  const g=isGroup(id)? GROUPS[id.slice(2)]: null;
  Object.entries(partEls).forEach(([k,e])=>e.classList.toggle("sel",g? g.parts.includes(k): k===id));
  Object.entries(hitEls).forEach(([k,e])=>e.classList.toggle("sel",!g&&(pipe? k===pipe: e.dataset.part===id)));
  document.querySelectorAll("#pid .zone").forEach(z=>z.classList.toggle("sel",!!g&&id==="g:"+z.dataset.group));
  gChips.querySelectorAll("button").forEach(b=>b.setAttribute("aria-pressed",id==="g:"+b.dataset.g?"true":"false"));
  buildReadings(); renderReadings(); readEl.scrollTop=0; drawPlots(true);
}
function buildReadings(){
  const g=isGroup(selected)? GROUPS[selected.slice(2)]: null, p=g||PARTS[selected];
  document.getElementById("pTitle").textContent=p.title;
  document.getElementById("pDesc").textContent=p.desc+(selPipe?" (Picked from a line of this part.)":"");
  pRowsEl.innerHTML=""; rowEls=[];
  let lastPart=null;
  for(const {r,part} of selRows()){
    if(g && part!==lastPart){ lastPart=part;
      const h=document.createElement("li"); h.className="grp";
      h.innerHTML=`<button type="button">${PARTS[part].title}</button><small>${(DATA.components[part]||[]).length} sensors</small>`;
      h.querySelector("button").addEventListener("click",()=>select(part)); pRowsEl.appendChild(h); }
    const li=document.createElement("li");
    li.innerHTML=`<span class="tag">${r.tag}</span><span class="d">${r.desc}</span><span class="val"></span><div class="rng" aria-hidden="true"></div><span class="note"></span>`
      +`<div class="plot${openPlot.has(r.col)?" big":""}" hidden><canvas role="img" aria-label="${r.tag} over the last 24 hours"></canvas><span class="pl"></span></div>`;
    const e={r,li,val:li.querySelector(".val"),rng:li.querySelector(".rng"),note:li.querySelector(".note"),plot:li.querySelector(".plot"),cv:li.querySelector("canvas"),pl:li.querySelector(".pl")};
    e.plot.addEventListener("click",()=>{ openPlot.has(r.col)? openPlot.delete(r.col): openPlot.add(r.col); e.plot.classList.toggle("big",openPlot.has(r.col)); drawPlots(true); });
    pRowsEl.appendChild(li); rowEls.push(e);
  }
}
function renderReadings(){
  const st=stage(S);
  for(const e of rowEls){ const r=e.r;
    const {v,f,knob,ease,rated}=shown(r,st), trip=TRIP[r.col];
    let bar="", note="";
    if(f){ const [,,p2,p10,,p90,p98,n]=f, lo=Math.min(p2,v??p2), hi=Math.max(p98,v??p98), span=(hi-lo)||1, X=x=>((x-lo)/span*100).toFixed(1)+"%";
      bar=`<div class="band" style="left:${X(p10)};width:calc(${X(p90)} - ${X(p10)})"></div>${v!=null?`<div class="dot" style="left:calc(${X(v)} - 1px)"></div>`:""}`;
      note=`${st==="Rated power"?"No plant data at rated power; part load":nm(st)}: plant p10–p90 ${fmt(p10,r.unit)}–${fmt(p90,r.unit)} ${r.unit}, ${n} min`; }
    else note=`No plant data for this sensor in ${nm(st)}.`;
    if(rated && !FEED.row) note=`Rated power value (30 A, 52 kW) from the part-load extrapolation (${r.rated.model}) · `+note;
    if(FEED.row) note="Data file · "+note;
    else if(CALC[r.col]) note="Twin model value · "+note;
    else if(knob && r.col!=="T_stack_C") note="Set by knob · "+note;
    if(r.col==="T_stack_C" && !FEED.row) note="Twin model value · "+note;
    if(ease){ const gone=S.t-ease.t0;
      note=(gone<ease.d?`Holds the ${ease.pst} level ${Math.ceil(ease.d-gone)} more min (plant delay), then moves over ${Math.round(ease.D)} min`
        :`Moving from the ${ease.pst} level ${ease.def?"at this sensor's usual plant pace (no plant timing for this change)":"at the plant's pace"}: ${Math.round(gone-ease.d)} of ${Math.round(ease.D)} min`)+" · "+note; }
    const bad=nearTrip(r.col,v);
    if(trip && v!=null) note+=` · trip ${trip} °C, margin ${Math.round(trip-v)} K`;
    e.li.className=bad?"trip":"";
    e.val.innerHTML=`${fmt(v,r.unit)}<small>${r.unit}</small>`;
    e.rng.innerHTML=bar; e.rng.hidden=!f;
    e.note.textContent=note;
  }
  drawPlots(false);
}

// ---------- time plots under each reading ----------
// A sensor gets a plot when its shown value changed over the last 24 h of twin time (range > 0.1 % of its size, min 0.01).
// Plot (170 px): axes, line, stage colour strip and trip line on the same 24 h axis as the stack trend. Tap → 380 px, finer grid.
// Redrawn at most 4× per second and only for plots on screen (the rest when scrolled into view).
const PLOT_WIN=1440, PLOT_MS=250;
let plotAt=0, plotTimer=null;
function drawPlots(force){
  const now=performance.now();
  if(!force && now-plotAt<PLOT_MS){ if(!plotTimer) plotTimer=setTimeout(()=>{ plotTimer=null; drawPlots(true); },PLOT_MS-(now-plotAt)); return; }
  plotAt=now; if(plotTimer){ clearTimeout(plotTimer); plotTimer=null; }
  const t0=S.t-PLOT_WIN, win=S.hist.filter(p=>p.t>=t0&&p.v);
  const box=readEl.getBoundingClientRect(), top=Math.max(0,box.top), bot=Math.min(window.innerHeight,box.bottom);
  let moving=0;
  for(const e of rowEls){
    const i=IDX.get(e.r.col); let lo=Infinity, hi=-Infinity;
    for(const p of win){ const x=p.v[i]; if(x===x){ if(x<lo) lo=x; if(x>hi) hi=x; } }
    const changes=win.length>1 && hi-lo>Math.max(0.01,1e-3*Math.max(Math.abs(hi),Math.abs(lo)));
    if(changes) moving++;
    e.plot.hidden=!changes;
    if(!changes) continue;
    const rc=e.cv.getBoundingClientRect();
    if(rc.bottom<top||rc.top>bot||!rc.width) continue;
    plotOne(e,win,i,lo,hi,t0);
  }
  const n=rowEls.length;
  document.getElementById("pSum").textContent=!win.length? `${n} sensor${n===1?"":"s"} · time plots appear once the twin runs (press Start plant or a stage button).`
    :`${n} sensor${n===1?"":"s"} · ${moving} changed in the last 24 h (plotted) · ${n-moving} steady (no plot).`;
}
function plotOne(e,win,i,lo,hi,t0){
  const c=e.cv, big=e.plot.classList.contains("big"), dpr=window.devicePixelRatio||1, w=c.clientWidth, h=c.clientHeight;
  if(c.width!==Math.round(w*dpr)||c.height!==Math.round(h*dpr)){ c.width=Math.round(w*dpr); c.height=Math.round(h*dpr); }
  const g=c.getContext("2d"); g.setTransform(dpr,0,0,dpr,0,0); g.clearRect(0,0,w,h);
  const u=e.r.unit, trip=TRIP[e.r.col], pad=(hi-lo)*0.08, y0=lo>=0? Math.max(0,lo-pad): lo-pad, y1=hi+pad;
  const L=52, R=10, Tp=8, B=26, pw=w-L-R, ph=h-Tp-B, t1=S.t;
  const X=t=>L+(t-t0)/PLOT_WIN*pw, Y=v=>Tp+ph-(v-y0)/(y1-y0)*ph;
  g.font="11px "+css("--f-mono"); g.lineWidth=1;
  { g.strokeStyle=css("--line"); g.fillStyle=css("--muted"); const nk=big?5:3;
    for(let k=0;k<=nk;k++){ const v=y0+(y1-y0)*k/nk, y=Y(v); g.beginPath(); g.moveTo(L,y+.5); g.lineTo(L+pw,y+.5); g.stroke(); g.textAlign="right"; g.fillText(fmt(v,u),L-5,y+3); }
    g.textAlign="center"; for(let k=Math.ceil(t0/240)*240;k<=t1;k+=240){ if(k<0) continue; g.fillText(String(Math.floor(k%1440/60)).padStart(2,"0")+":00",X(k),h-4); }
    if(trip&&trip>=y0&&trip<=y1){ g.setLineDash([4,4]); g.strokeStyle=css("--warn"); g.beginPath(); g.moveTo(L,Y(trip)); g.lineTo(L+pw,Y(trip)); g.stroke(); g.setLineDash([]);
      g.fillStyle=css("--warn"); g.textAlign="left"; g.fillText(`trip ${trip} °C`,L+4,Y(trip)-4); }
  }
  win.forEach((p,k)=>{ const nx=k<win.length-1?X(win[k+1].t):X(p.t)+1; g.fillStyle=STAGES[p.st]; g.fillRect(X(p.t),h-B+3,Math.max(1,nx-X(p.t)+.5),5); });
  g.strokeStyle=css("--chart"); g.lineWidth=2; g.beginPath(); let prev=null;
  for(const p of win){ const v=p.v[i]; if(v!==v){ prev=null; continue; } const x=X(p.t), y=Y(v); prev!=null&&p.t-prev<=2? g.lineTo(x,y): g.moveTo(x,y); prev=p.t; }
  g.stroke();
  for(let k=win.length-1;k>=0;k--){ const v=win[k].v[i]; if(v===v){ g.fillStyle=css("--chart"); g.beginPath(); g.arc(X(win[k].t),Y(v),3.5,0,7); g.fill(); break; } }
  e.pl.textContent=big? `24 h range ${fmt(lo,u)} – ${fmt(hi,u)} ${u} · tap to make small`: `24 h: ${fmt(lo,u)} – ${fmt(hi,u)} ${u} · tap to enlarge`;
}
let scrollRaf=0;
const onScroll=()=>{ if(!scrollRaf) scrollRaf=requestAnimationFrame(()=>{ scrollRaf=0; drawPlots(true); }); };
readEl.addEventListener("scroll",onScroll,{passive:true});
window.addEventListener("scroll",onScroll,{passive:true});

// ---------- stage bar: jump straight into a stage ----------
// Stage order of the stage bar; flows for a move = plant medians per stage (plant_stages_1min.parquet, 39 days).
// Stage bar (v3.0): Heat up → Hot standby → Part load → Rated power, then Air flow cooling, Shutdown, Trip. Button keys:
// "Heat-up air" = Heat up (start / restart), "Fuel switch" = Hot standby.
const ORDER=["Heat-up air","Fuel switch","Part load","Rated power","Air-flow cooling","Shutdown"];
// Linked stages (no jump, only the real move from the stage before):
//   Hot standby  comes by itself when the heat up ends (~506 °C on N₂ + H₂: natural gas opens, no current);
//                from part load or rated power: current off, gas stays on
//   Part load    from hot standby: button only
//   Rated power  from part load: button only; it stays until a button is pressed, and any button then goes to hot standby
// Heat up, Air flow cooling and Shutdown are real moves from the current stack temperature too (moveStep), not jumps.
const LINK_HINT={"Fuel switch":"after heat up","Part load":"from hot standby","Rated power":"from part load"};
const LINK_FROM={"Fuel switch":["Heat-up air","Part load","Rated power"],"Part load":["Fuel switch"],"Rated power":["Part load"]};
const LINK_PATH="Start plant → Heat up (air, then N₂+H₂) → Hot standby → Part load → Rated power";
function linkStep(cur,st){
  if(cur===st) return {msg:`Already in ${lc(nm(st))}.`};
  if(S.trip>0) return {msg:`Emergency purge running: the twin goes back to hot standby by itself when it ends.`};
  if(S.estop) return {msg:`After an emergency stop the plant restarts from shutdown: ${LINK_PATH}.`};
  if(cur==="Rated power" && st!=="Fuel switch")
    return {act:()=>toStandby(S), msg:`Rated power goes to hot standby first (current 0, natural gas stays on, air ${F("Fuel switch").air|0} ln/min, air heater ${SP_FS} °C); ${lc(nm(st))} from there.`};
  if(st==="Fuel switch" && nm(cur)==="Heat up")
    return {msg:`Hot standby comes by itself when the heat up ends near ${SP_HS} °C (now ${Math.round(S.T)} °C, ${S.dT>=0?"+":"−"}${Math.abs(S.dT).toFixed(0)} °C/h): natural gas opens, no current.`};
  if(st==="Fuel switch" && LOADS.includes(cur))
    return {act:()=>toStandby(S), msg:`Back to hot standby: current 0 (no power drawn), natural gas ${F("Fuel switch")[14]|0} and POx ${F("Fuel switch")[12]|0} ln/min stay on, air ${F("Fuel switch").air|0} ln/min, air heater ${SP_FS} °C.`};
  if((st==="Part load" && cur==="Fuel switch") || (st==="Rated power" && cur==="Part load"))
    return {act:()=>toLoad(S,st), msg:loadMsg(st)};
  return {msg:`${nm(st)} is a linked stage: no jump, it is reached only from ${LINK_FROM[st].map(x=>lc(nm(x))).join(" or ")} (${LINK_PATH}). Now in ${lc(nm(cur))}.`};
}
function jump(st){
  // Part load and rated power are always followed by hot standby (a trip purge is the only other way out): from there, a
  // stage-bar click on any other stage unloads the plant to hot-standby settings instead of jumping there.
  const cur=stage(S);
  if(LOADS.includes(cur) && !LOADS.includes(st) && st!=="Fuel switch"){
    play=null; toStandby(S); S.plWas=false; S.rejAt=S.t;
    playMsg=`${nm(cur)} is always followed by hot standby (except a trip), so not straight to ${lc(nm(st))}: current 0, natural gas stays on, air ${Math.round(S.air)} ln/min, heaters on, air heater ${SP_FS} °C. From hot standby you can go on to ${lc(nm(st))}.`;
    render(); return;
  }
  // Linked stages: no jump, only the real move from the stage before (or a message why not).
  if(st in LINK_HINT){
    const k=linkStep(cur,st);
    if(k.act){ play=null; S.estop=false; k.act(); applyRules(S); followPartLoad(S); if(k.msg) playMsg=k.msg; }
    else { playMsg=k.msg; S.rejAt=S.t; }
    render(); return;
  }
  // Heat-up air, Air-flow cooling, Shutdown: real moves from the stack temperature the twin has now, never a jump.
  const k=moveStep(cur,st);
  if(k.act){ play=null; k.act(); if(k.msg) playMsg=k.msg; }
  else { playMsg=k.msg; S.rejAt=S.t; }
  render();
}
// No stage-bar jumps any more (2026-11-04, user): the plant data (operating_states.ipynb §12.9) shows the stack going from
// hot standby, heat-up and air-flow cooling into shutdown gradually, so the twin no longer sets the stack to a stage median
// (the old jumps put it at 44 °C for Shutdown, 242 °C for Air-flow cooling, 159 °C for Heat-up air in one minute).
// Plant entries into shutdown (air off), stack °C after 1 / 3 / 6 h: 30 Jan from air-flow cooling 198 → 194 / 190 / 185,
// 17 Feb 210 → 206 / 202 / 197, 17 Mar from heat-up air 188 → 190 / 185 / 178, 30 Oct from heat-up N₂+H₂ 199 → 198 / 195 / 188:
// about −2 °C/h with the air off; the twin's air-off loss (LOSS) gives −2.1 °C/h at 200 °C.
//   Shutdown          heaters, gas, current and air off (N₂ + H₂ by the 210 °C rule); the stack cools slowly from where it is
//   Air-flow cooling  heaters, gas and current off, plant median air; from hot standby with the plant's cooling slope
//   Heat-up air       from shutdown = Start plant; while cooling down below hot standby = restart (heat-up air or N₂+H₂ by temperature)
// Part load and rated power first unload to hot standby (rule above); a running purge locks these moves.
function moveStep(cur,st){
  const T=Math.round(S.T);
  if(cur===st) return {msg:`Already in ${lc(nm(st))}.`};
  if(S.trip>0) return {msg:"Emergency purge running: the twin goes back to hot standby by itself when it ends."};
  if(st==="Shutdown") return {act:()=>{
      Object.assign(S,{heaters:false,air:0,ng:0,pox:0,I:0,fgAuto:true,estop:false,kept:false,plWas:false}); applyRules(S);
    }, msg:`Shutdown from ${lc(nm(cur))} at ${T} °C: heaters, gas, current and air off (N₂ + H₂ by the ${T_FORMING} °C rule). No jump: the stack cools slowly from ${T} °C by itself, as in the plant data (air off, about −2 °C/h near 200 °C, twin ${(-LOSS*(S.T-T_AMB)).toFixed(1)} °C/h now).`};
  if(st==="Air-flow cooling") return {act:()=>{
      Object.assign(S,{heaters:false,air:F(st).air||6000,ng:0,pox:0,I:0,fgAuto:true,estop:false,kept:false,plWas:false}); applyRules(S);
    }, msg:cur==="Fuel switch"
      ?`Cooling from hot standby at ${T} °C: natural gas and heaters off, air ${Math.round(F(st).air||6000)} ln/min. ${S.plantCool?`The stack follows the plant's hot standby → cooling slope (POC data): about ${Math.round(-HSC_C6*Math.pow((F(st).air||6000)/6000,HSC_N)*(S.T-T_AMB)*Math.sqrt(Math.max(S.T-T_AMB,0)/475))} °C/h after the first few minutes, slower as it cools.`:"Cooling slope from the heat balance (plant slope switched off)."}`
      :`Air-flow cooling from ${lc(nm(cur))} at ${T} °C: heaters, gas and current off, air ${Math.round(F(st).air||6000)} ln/min. No jump: the stack cools from ${T} °C at the heat-balance rate.`};
  if(st==="Heat-up air"){
    if(canRestart(S)) return {act:()=>warmStart(S)};
    if(cur==="Shutdown") return {act:()=>startNow()};
    return {msg:`Heat up starts from shutdown (Start plant) or from a cool-down below ${SP_HS} °C; now in ${lc(nm(cur))} at ${T} °C.`};
  }
  return {msg:`No move to ${lc(nm(st))} from ${lc(nm(cur))}.`};
}
const MOVE_HINT={"Heat-up air":"start / restart","Air-flow cooling":"heaters off","Shutdown":"air off"};
const stBar=document.getElementById("stages");
// after Rated power the arrow points back to hot standby (part load / rated power → hot standby, except a trip)
stBar.innerHTML=ORDER.map((s,i)=>`${!i?"":ORDER[i-1]==="Rated power"?'<span class="arr back" title="Part load and rated power are always followed by hot standby (except a trip)">↩ Hot standby</span><span class="sep" aria-hidden="true"></span>':'<span class="arr" aria-hidden="true">→</span>'}<button type="button" data-stage="${s}"${s in LINK_HINT?' data-link="1"':""}><i style="background:${STAGES[s]}"></i>${nm(s)}<small>${s in LINK_HINT?LINK_HINT[s]:MOVE_HINT[s]}</small></button>`).join("")
  +`<span class="sep" aria-hidden="true"></span><button type="button" data-stage="Trip: purge" data-purge="1"><i style="background:${STAGES["Trip: purge"]}"></i>${nm("Trip: purge")}<small>from HS / PL / RP</small></button>`;
stBar.querySelectorAll("button").forEach(b=>b.onclick=()=>b.dataset.purge?tripNow():jump(b.dataset.stage));

// ---------- knobs ----------
const KN=[["air","Cathode air","--air",0,10000,500,"ln/min"],["pox","POx air","--pox",0,700,10,"ln/min"],["n2","Nitrogen","--n2",0,1300,50,"ln/min"],
  ["h2","Hydrogen","--h2",0,70,5,"ln/min"],["ng","Natural gas","--ng",0,250,5,"ln/min"],["I","Current per string","--elec",0,42,0.1,"A"],["target","Air heater target","--heat",100,700,10,"°C"]];
const kWrap=document.getElementById("knobs");
kWrap.innerHTML=KN.map(([k,n,c,mi,ma,st])=>`<div class="row"><div class="hd"><label for="k_${k}"><i style="background:var(${c})"></i>${n}</label><span class="num" id="v_${k}"></span></div><input type="range" id="k_${k}" min="${mi}" max="${ma}" step="${st}"></div>`).join("");
// current knob: only in part load / rated power (both by button only); in part load it stays below rated power
KN.forEach(([k])=>document.getElementById("k_"+k).addEventListener("input",e=>{ manual(); if(k==="n2"||k==="h2") S.fgAuto=false; S[k]=+e.target.value;
  if(k==="I"&&stage(S)==="Part load") S.I=Math.min(S.I,I_RATED_MIN); applyRules(S); followPartLoad(S); render(); }));
const $=id=>document.getElementById(id);
$("hOn").onclick=()=>{manual(); S.heaters=true; followPartLoad(S); render();};
$("hOff").onclick=()=>{manual(); S.heaters=false; followPartLoad(S); render();};
$("fgA").onclick=()=>{manual(); S.fgAuto=true; applyRules(S); followPartLoad(S); render();};
$("fgM").onclick=()=>{manual(); S.fgAuto=false; followPartLoad(S); render();};
$("jOn").onclick=()=>{ jerkOn=true; render(); };
$("jOff").onclick=()=>{ jerkOn=false; snapSensors(); render(); };
$("kpOn").onclick=()=>{ S.keeper=true; render(); };
$("kpOff").onclick=()=>{ S.keeper=false; S.kept=false; render(); };
// cooling after hot standby: plant slope or heat balance. Off during a cooling hands over to the heat balance at once;
// On applies from the next hot-standby exit.
$("pcOn").onclick=()=>{ S.plantCool=true; render(); };
$("pcOff").onclick=()=>{ S.plantCool=false; render(); };
// Go to part load / Go to rated power = the same linked moves as the stage-bar buttons
const GO={load:"Part load",rated:"Rated power"};
document.querySelectorAll("[data-scen]").forEach(b=>b.onclick=()=>{
  if(GO[b.dataset.scen]) return jump(GO[b.dataset.scen]);
  S.trip=0; S.estop=false; startPlay(b.dataset.scen); applyRules(S); followPartLoad(S); render(); });
function tripNow(){ if(S.trip<=0 && !startPurge(S,`Trip from ${lc(nm(stage(S)))}: emergency purge ${PURGE_MIN} min, then back to hot standby.`)){ playMsg=noPurgeMsg(S); S.rejAt=S.t; } render(); }
$("tripBtn").onclick=tripNow;
// Emergency stop (any stage, also during a purge): everything off at once, air included: air, N₂, H₂, natural gas, POx,
// current and heaters. The N₂ + H₂ rule is switched to manual so it does not reopen the forming gas. The stage reads
// Shutdown (air off) and the stack cools slowly by itself. Any knob, playbook, stage-bar click or Start plant resets it.
function eStop(){
  play=null;
  Object.assign(S,{trip:0,air:0,pox:0,n2:0,h2:0,ng:0,I:0,heaters:false,fgAuto:false,kept:false,plWas:false,estop:true,noPurgeWarn:false,rejAt:null});
  playMsg=`Emergency stop at ${Math.round(S.T)} °C: everything off, air included (air, N₂, H₂, natural gas, POx, current, heaters). The stack now cools slowly with no air. Start plant, Shut down, a knob or a stage-bar click resets the twin.`;
  render();
}
$("estopBtn").onclick=eStop;
// Start plant: the plant always starts from ambient. Allowed only from shutdown; if the stack is still warm there
// (e.g. just after Shut down, air off below 40 °C, or after an emergency stop), the twin first sets the plant to ambient (stack, air-in,
// recuperator 25 °C, all flows off) and then runs the plant cold-start settings.
const START_FROM=["Shutdown"];
const canStart=s=>s.trip<=0&&START_FROM.includes(stage(s));
function toAmbient(s){
  Object.assign(s,{T:T_AMB,Tin:T_AMB,dT:0,slope:0,air:0,pox:0,n2:0,h2:0,ng:0,I:0,heaters:false,fgAuto:true,kept:false,plWas:false,estop:false,rsAt:null,reheat:false});
  s.Rb=null; followRec(s,0); applyRules(s); snapSensors();
}
// Restart during a cool-down below hot standby (see canRestart): heat-up from today's stack temperature, the stage by temperature.
function warmStart(s){
  const from=s.dT, was=Math.round(s.T), st=s.T>=T_FORMING?"Heat-up N₂+H₂":"Heat-up air";
  Object.assign(s,{estop:false,rejAt:null,kept:false,plWas:false,coolAt:null});
  startPlay("cold"); applyRules(s);                       // plant cold-start settings; at 210 °C and up the 500 °C step runs at once
  Object.assign(s,{rsAt:s.t,rsFrom:from,rsD:RS_D[st],reheat:st==="Heat-up N₂+H₂"});
  playMsg=`Restart during the cool-down at ${was} °C (below ${SP_HS} °C) → ${lc(nmp(st))}: air ${Math.round(s.air)} ln/min, heaters on, `
    +(st==="Heat-up air"?`air heater 300 °C (500 °C and N₂ + H₂ from ${T_FORMING} °C).`:`N₂ + H₂ on, air heater 500 °C.`)
    +` As on the plant, the air heater ramps 60 °C/h from today's air-in (${Math.round(s.Tin)} °C); the stack slope blends smoothly from ${from>=0?"+":"−"}${Math.abs(from).toFixed(0)} °C/h into the heat-up slope over ${s.rsD} min (plant bend time).`;
}
function startNow(){
  if(canRestart(S)){ warmStart(S); render(); return; }
  if(!canStart(S)){ playMsg=S.trip>0?"Start is locked while the emergency purge runs."
      :coolingDown(S)?`Stack ${Math.round(S.T)} °C is still above ${SP_HS} °C: a restart during the cool-down works once the stack is below ${SP_HS} °C (heat up on air below ${T_FORMING} °C, on N₂+H₂ above).`
      :`The plant is not in shutdown (${lc(nm(stage(S)))}): Start works only from shutdown, or while cooling down below ${SP_HS} °C.`; S.rejAt=S.t; render(); return; }
  const warm=S.T-T_AMB>=1, was=Math.round(S.T);
  S.rejAt=null; toAmbient(S); startPlay("cold"); applyRules(S);
  if(warm) playMsg=`Stack was ${was} °C: plant set to ambient ${T_AMB} °C first (start always from ambient). `+playMsg;
  render();
}
$("startBtn").onclick=startNow;

// ---------- render ----------
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
function stackColor(T){ const f=Math.min(1,Math.max(0,(T-T_AMB)/775)), m=(a,b)=>Math.round(a+(b-a)*f); return `rgb(${m(111,217)} ${m(130,84)} ${m(150,30)})`; }
function render(){
  const st=stage(S);
  const d=Math.floor(S.t/1440)+1, hh=String(Math.floor(S.t%1440/60)).padStart(2,"0"), mm=String(Math.floor(S.t%60)).padStart(2,"0");
  $("clock").textContent=FEED.mode==="twin"? `Day ${d} · ${hh}:${mm}`: feedClock(`Day ${d} · ${hh}:${mm}`);
  $("stage").querySelector("i").style.background=STAGES[st]; $("stage").querySelector("span").textContent=nmp(st)+(S.estop?" · emergency stop":"");
  stBar.querySelectorAll("button").forEach(b=>{ if(nm(b.dataset.stage)===nm(st)) b.setAttribute("aria-current","step"); else b.removeAttribute("aria-current"); });
  stBar.querySelectorAll("[data-link]").forEach(b=>{ const k=linkStep(st,b.dataset.stage); b.setAttribute("aria-disabled",k.act?"false":"true"); b.title=k.msg; });
  const ld=LOADS.includes(st);   // current knob: part load only (rated power holds its current until a button is pressed)
  stBar.querySelectorAll("button[data-stage]:not([data-link]):not([data-purge])").forEach(b=>{ const t=b.dataset.stage, k=ld?{act:1}:moveStep(st,t);
    b.setAttribute("aria-disabled",k.act?"false":"true"); b.title=ld?`${nm(st)} unloads to hot standby first`:k.act?`Go to ${lc(nm(t))} from ${Math.round(S.T)} °C (no jump)`:k.msg; });
  Object.entries(GO).forEach(([g,n])=>{ const b=document.querySelector(`[data-scen="${g}"]`), k=linkStep(st,n); b.setAttribute("aria-disabled",k.act?"false":"true"); b.title=k.msg; });
  $("tStack").textContent=Math.round(S.T); $("slope").textContent=(S.dT>=0?"+":"−")+Math.abs(S.dT).toFixed(0);
  const erh=val("TIRZ_8_2_5"), stz=val("TIRZ_8_1_3"), want=S.T>T_FORMING&&!ngOn(S), fg=fgOn(S);
  const chk=[
    {ok:S.trip>0||fg===want, txt:S.trip>0||fg===want?"N₂ + H₂ match the 210 °C rule":S.estop?"Emergency stop: N₂ + H₂ off above 210 °C":`N₂ + H₂ ${fg?"on":"off"} breaks the 210 °C rule`},
    {ok:erh==null||erh<820, txt:`ERH safety ${erh==null?"–":Math.round(erh)} °C (trip 860)`},
    {ok:stz==null||stz<690, txt:`Stack safety ${stz==null?"–":Math.round(stz)} °C (trip 720)`},
    {ok:!(ngOn(S)&&S.T<450), txt:ngOn(S)&&S.T<450?"Natural gas on a cold stack":"Gas only on a hot stack"},
  ];
  $("checks").innerHTML=chk.map(c=>`<li class="${c.ok?"":"bad"}"><b></b><span>${c.txt}</span></li>`).join("");
  PIPES.forEach(([id,,,,on])=>flowEls[id].classList.toggle("on",!!on(S)));
  HEATERS.forEach(h=>partEls[h].classList.toggle("hot",heatOn(S)));
  Object.entries(partEls).forEach(([k,e])=>e.classList.toggle("alarm",(DATA.components[k]||[]).some(r=>nearTrip(r.col,val(r.col)))));
  $("stackShape").setAttribute("fill",stackColor(S.T)); $("stackShape").style.fill=stackColor(S.T);
  live.stack.textContent=`${Math.round(S.T)} °C`;
  live.air.textContent=`${Math.round(S.air/2)} + ${Math.round(S.air/2)} ln/min`;
  live.pox.textContent=`${Math.round(S.pox)} ln/min`; live.h2.textContent=`${Math.round(S.h2)} ln/min`; live.n2.textContent=`${Math.round(S.n2)} ln/min`; live.ng.textContent=`${Math.round(S.ng)} ln/min`;
  const v=(c)=>{const x=val(c); return x==null?"–":Math.round(x);};
  live.eaph.textContent=`${v("TIRC_2_06")} °C`; live.erh.textContent=`${v("TIRC_5_17")} °C`; live.eagh.textContent=`${v("TIRC_3_1_1")} °C`;
  live.tox.textContent=`${v("TIRC_5_09")} °C`; live.eaoh.textContent=`${v("TIRC_6_1_1")} °C`;
  const pct=c=>{ const x=val(c); return x==null?"η –":`η ${x.toFixed(1)} %`; };
  live.dcdc.forEach(([tI,tV,tP,tE],k)=>{ const I=val(STR[k][0])??0, V=val(STR[k][1])??0;
    tI.textContent=`${I.toFixed(1)} A`; tV.textContent=`${Math.round(V)} V`; tP.textContent=`${(V*I/1000).toFixed(2)} kW`; tE.textContent=pct(`eta_string${k+1}_pct`); });
  const [lP,lV,lI,lE]=live.load;
  lP.textContent=`${(val("P_total_kW")??0).toFixed(1)} kW`; lV.textContent=`${Math.round(val("V_total_V")??0)} V`; lI.textContent=`${(val("I_total_A")??0).toFixed(1)} A`; lE.textContent=pct("eta_module_pct");
  KN.forEach(([k,,,,,,u])=>{ const i=$("k_"+k); i.value=S[k]; $("v_"+k).textContent=`${k==="I"?S[k].toFixed(1):Math.round(S[k])} ${u}`; });
  const rOk=canRestart(S), sOk=canStart(S)||rOk, sb=$("startBtn");
  sb.setAttribute("aria-disabled",sOk?"false":"true");
  sb.title=rOk?`Restart from ${Math.round(S.T)} °C (below ${SP_HS} °C): ${S.T>=T_FORMING?"heat up on N₂+H₂, air heater 500 °C":"heat up on air, air heater 300 °C"}, smooth slope turn`
    :sOk?"Cold start from ambient 25 °C: air 6000 ln/min, heaters on, air heater 300 °C, then 500 °C and N₂+H₂ from 210 °C; at the end natural gas opens (hot standby)":`Start works only from shutdown, or while cooling down below ${SP_HS} °C`;
  const pOk=canPurge(S);
  [$("tripBtn"),stBar.querySelector("[data-purge]")].forEach(b=>{ b.setAttribute("aria-disabled",pOk?"false":"true"); b.title=pOk?`Emergency purge ${PURGE_MIN} min, then back to hot standby`:S.trip>0?"Purge running":S.estop?"Locked after an emergency stop":"Trip / emergency purge only from hot standby, part load or rated power"; });
  $("k_I").disabled=st!=="Part load"; $("k_n2").disabled=$("k_h2").disabled=S.fgAuto||S.trip>0;
  [["hOn",S.heaters],["hOff",!S.heaters],["fgA",S.fgAuto],["fgM",!S.fgAuto],["jOn",jerkOn],["jOff",!jerkOn],["kpOn",S.keeper],["kpOff",!S.keeper],["pcOn",S.plantCool],["pcOff",!S.plantCool]].forEach(([id,on])=>$(id).setAttribute("aria-pressed",on?"true":"false"));
  $("scenLbl").textContent=S.rejAt!=null&&S.t-S.rejAt<5?playMsg:S.trip>0?`Emergency purge: air, N₂ and H₂ only, ${Math.ceil(S.trip)} min left.`
    :playMsg;
  $("slopeSrc").textContent=FEED.row? `From the data file · slope over 10 min · air in ${Math.round(S.Tin)} °C`: `Heat balance · air in ${Math.round(S.Tin)} °C`+(S.rsAt!=null?` · stage change: slope blending in, ${S.t-S.rsAt} of ${S.rsD} min (plant bend time)`:"")+(S.kept?` · keeper holding ${KEEP} °C (air ${Math.round(S.air)}, target ${Math.round(S.target)} °C)`:"");
  renderReadings(); drawTrend(); renderBend();
}
// ---------- bend panel ----------
const sgn=v=>v==null||!isFinite(v)?"–":(v>=0?"+":"−")+Math.abs(v).toFixed(Math.abs(v)<10?1:0);
const bendTxt=b=>!b?"no clear bend":b[0]<=-20?"turned before −20 min":b[1]-b[0]===0?`step at ${b[0]>=0?"+":"−"}${Math.abs(b[0])} min`:`${b[1]-b[0]} min (${b[0]>=0?"+":"−"}${Math.abs(b[0])} → ${b[1]>=0?"+":"−"}${Math.abs(b[1])})`;
const num=(v,d=2)=>v==null||!isFinite(v)?"–":v.toFixed(d);
function renderBend(){
  const b=S.border;
  if(!b){ $("bTitle").textContent="No stage change yet"; $("bNote").textContent=""; $("bTab").innerHTML=""; drawBend(null,null); markAll(null); return; }
  const P=plantBend(b), tw=twinBend(b), ps=P&&P.sig.stack, ph=P&&P.sig.heaters;
  const d=Math.floor(b.t/1440)+1, hh=String(Math.floor(b.t%1440/60)).padStart(2,"0"), mm=String(b.t%60).padStart(2,"0");
  $("bTitle").textContent=`${nmp(b.from)} → ${nmp(b.to)}`;
  const since=S.t-b.t+1;
  $("bNote").textContent=`Day ${d} · ${hh}:${mm}, ${since} min ago. `
    +(P?`The plant made this change ${P.n}× cleanly in 39 days.`:"The plant never made this change cleanly in the 39 days, so there is nothing to compare with.")
    +(b.jump?" Started by a stage-bar jump: the twin has no “before” side.":"")
    +(tw&&tw.after<BW?` Twin “after” slope uses the first ${tw.after} min so far.`:"")
    +(Object.keys(EASE).length?` ${Object.keys(EASE).length} slower sensors are still moving to the new stage level at the plant's pace.`:"");
  const row=(n,a,c,e)=>`<tr><td>${n}</td><td>${a}</td><td>${c}</td><td>${e}</td></tr>`;
  $("bTab").innerHTML=`<tr><th></th><th>Plant stack</th><th>Twin stack</th><th>Plant heaters</th></tr>`
    +row("Slope before, °C/h", sgn(ps?.pre), sgn(tw?.pre), sgn(ph?.pre))
    +row("Slope after, °C/h", sgn(ps?.post), sgn(tw?.post), sgn(ph?.post))
    +row("Bend, °C/h", sgn(ps&&ps.post-ps.pre), sgn(tw&&tw.pre!=null&&tw.post!=null?tw.post-tw.pre:null), sgn(ph&&ph.post-ph.pre))
    +row("Bend time", ps?bendTxt(ps.bend):"–", tw?(tw.bend?bendTxt(tw.bend):tw.after<BW+10||tw.pre==null?"–":"no clear bend"):"–", ph?bendTxt(ph.bend):"–")
    +row("Peak acceleration, °C/h per min", num(ps?.acc), num(tw?.acc), num(ph?.acc))
    +row("Peak jerk, °C/h per min²", num(ps?.jerk), num(tw?.jerk), num(ph?.jerk));
  drawBend(ps,tw); markAll(b);
}
function drawBend(ps,tw){
  const c=$("bChart"), dpr=window.devicePixelRatio||1, w=c.clientWidth, h=c.clientHeight;
  if(!w) return;
  if(c.width!==w*dpr||c.height!==h*dpr){ c.width=w*dpr; c.height=h*dpr; }
  const g=c.getContext("2d"); g.setTransform(dpr,0,0,dpr,0,0); g.clearRect(0,0,w,h);
  const t0=BENDS.tm[0], t1=BENDS.tm[1], ys=[...(ps?ps.curve:[]),...(tw?tw.y:[])].filter(v=>v!=null&&isFinite(v));
  const lo=Math.min(-10,...ys), hi=Math.max(10,...ys), L=44,R=10,Tp=8,B=26,pw=w-L-R,ph=h-Tp-B;
  const X=t=>L+(t-t0)/(t1-t0)*pw, Y=v=>Tp+ph-(v-lo)/(hi-lo)*ph;
  g.font="11px "+css("--f-mono"); g.fillStyle=css("--muted"); g.strokeStyle=css("--line"); g.lineWidth=1;
  const stp=[5,10,20,50,100,200].find(s=>(hi-lo)/s<=6)||500;
  for(let v=Math.ceil(lo/stp)*stp;v<=hi;v+=stp){ g.beginPath(); g.moveTo(L,Y(v)+.5); g.lineTo(L+pw,Y(v)+.5); g.stroke(); g.textAlign="right"; g.fillText((v>0?"+":"")+v+"°",L-6,Y(v)+4); }
  g.textAlign="center"; for(let t=-45;t<=60;t+=15) g.fillText((t>0?"+":"")+t,X(t),h-8);
  g.setLineDash([4,4]); g.strokeStyle=css("--muted"); g.beginPath(); g.moveTo(X(0)+.5,Tp); g.lineTo(X(0)+.5,Tp+ph); g.stroke(); g.setLineDash([]);
  g.textAlign="left"; g.fillText("stage change · min",X(0)+4,Tp+10);
  if(ps?.bend){ g.fillStyle=css("--heat"); g.globalAlpha=.18; g.fillRect(X(ps.bend[0]),Tp,Math.max(2,X(ps.bend[1])-X(ps.bend[0])),ph); g.globalAlpha=1; }
  const line=(xs,vs,col)=>{ g.strokeStyle=col; g.lineWidth=2; g.beginPath(); let on=false; vs.forEach((v,i)=>{ if(v==null||!isFinite(v)){ on=false; return; } on?g.lineTo(X(xs[i]),Y(v)):g.moveTo(X(xs[i]),Y(v)); on=true; }); g.stroke(); };
  if(ps) line(ps.curve.map((_,i)=>t0+i),ps.curve,css("--heat"));
  if(tw) line(tw.tm,tw.y,css("--chart"));
  if(!ps&&!tw){ g.textAlign="center"; g.fillStyle=css("--muted"); g.fillText("no stage change yet",L+pw/2,Tp+ph/2); }
}
const ALL=BENDS.borders.filter(e=>e.sig.stack);
$("bAll").innerHTML=`<tr><th>Border</th><th>n</th><th>Stack °C/h</th><th>Bend time</th><th>Jerk</th></tr>`
  +ALL.map((e,i)=>{ const s=e.sig.stack; return `<tr data-i="${i}"><td>${nmp(e.from)} → ${nmp(e.to)}</td><td>${e.n}</td><td>${sgn(s.pre)} → ${sgn(s.post)}</td><td>${s.bend?`${s.bend[1]-s.bend[0]} min`:"–"}</td><td>${num(s.jerk)}</td></tr>`; }).join("");
function markAll(b){ $("bAll").querySelectorAll("tr[data-i]").forEach(r=>{ const e=ALL[+r.dataset.i]; r.classList.toggle("cur",!!b&&e.from===b.from&&e.to===b.to); }); }
function drawTrend(){
  const c=$("trend"), dpr=window.devicePixelRatio||1, w=c.clientWidth, h=c.clientHeight;
  if(!w) return;
  if(c.width!==w*dpr||c.height!==h*dpr){ c.width=w*dpr; c.height=h*dpr; }
  const g=c.getContext("2d"); g.setTransform(dpr,0,0,dpr,0,0); g.clearRect(0,0,w,h);
  const pts=S.hist.filter(p=>p.t>=S.t-1440), top=Math.max(900,Math.ceil(Math.max(0,...pts.map(p=>p.T))/100)*100);   // scale grows with the stack (rated power can pass 900 °C)
  const L=44,R=10,Tp=8,B=34,pw=w-L-R,ph=h-Tp-B,t1=S.t,t0=t1-1440, X=t=>L+(t-t0)/1440*pw, Y=T=>Tp+ph-(T/top)*ph;
  g.font="11px "+css("--f-mono"); g.fillStyle=css("--muted"); g.strokeStyle=css("--line"); g.lineWidth=1;
  for(let v=0;v<top;v+=200){ g.beginPath(); g.moveTo(L,Y(v)+.5); g.lineTo(L+pw,Y(v)+.5); g.stroke(); g.textAlign="right"; g.fillText(v+"°",L-6,Y(v)+4); }
  g.textAlign="center"; for(let k=Math.ceil(t0/240)*240;k<=t1;k+=240){ if(k<0) continue; g.fillText(String(Math.floor(k%1440/60)).padStart(2,"0")+":00",X(k),h-6); }
  g.setLineDash([4,4]); g.strokeStyle=css("--n2"); g.beginPath(); g.moveTo(L,Y(210)); g.lineTo(L+pw,Y(210)); g.stroke(); g.setLineDash([]);
  g.fillStyle=css("--n2"); g.textAlign="left"; g.fillText("210 °C forming gas",L+4,Y(210)-5);
  pts.forEach((p,i)=>{ const nx=i<pts.length-1?X(pts[i+1].t):X(p.t)+1; g.fillStyle=STAGES[p.st]; g.fillRect(X(p.t),h-B+4,Math.max(1,nx-X(p.t)+.5),8); });
  if(S.border&&S.border.t>=t0){ g.setLineDash([3,3]); g.strokeStyle=css("--muted"); g.lineWidth=1; g.beginPath(); g.moveTo(X(S.border.t)+.5,Tp); g.lineTo(X(S.border.t)+.5,Tp+ph); g.stroke(); g.setLineDash([]); }
  if(pts.length>1){ const col=css("--chart"), gr=g.createLinearGradient(0,Tp,0,Tp+ph); gr.addColorStop(0,`color-mix(in srgb, ${col} 33%, transparent)`); gr.addColorStop(1,`color-mix(in srgb, ${col} 0%, transparent)`);   // theme colours are oklch: no hex alpha
    g.beginPath(); pts.forEach((p,i)=>i?g.lineTo(X(p.t),Y(p.T)):g.moveTo(X(p.t),Y(p.T))); g.lineTo(X(pts[pts.length-1].t),Tp+ph); g.lineTo(X(pts[0].t),Tp+ph); g.fillStyle=gr; g.fill();
    g.strokeStyle=col; g.lineWidth=2; g.beginPath(); pts.forEach((p,i)=>i?g.lineTo(X(p.t),Y(p.T)):g.moveTo(X(p.t),Y(p.T))); g.stroke();
    const e=pts[pts.length-1]; g.fillStyle=col; g.beginPath(); g.arc(X(e.t),Y(e.T),3.5,0,7); g.fill(); }
  drawPower(pts,t0,t1);
}
// Load bank total power under the stack trend: Σ V × I of the 5 strings from each recorded minute (same 24 h axis).
const PW_IDX=[1,2,3,4,5].map(n=>[IDX.get(`PLC_hostSetp_ctrl_ctEIRC4${n}_rCurrMonitor`),IDX.get(`PLC_hostSetp_ctrl_ctEIRC4${n}_rVoltMonitor`)]);
const kW=v=>PW_IDX.reduce((s,[i,u])=>s+((v[i]||0)*(v[u]||0)),0)/1000;   // NaN (no reading) counts as 0
function drawPower(pts,t0,t1){
  const c=$("power"), dpr=window.devicePixelRatio||1, w=c.clientWidth, h=c.clientHeight;
  if(!w) return;
  if(c.width!==w*dpr||c.height!==h*dpr){ c.width=w*dpr; c.height=h*dpr; }
  const g=c.getContext("2d"); g.setTransform(dpr,0,0,dpr,0,0); g.clearRect(0,0,w,h);
  const ps=pts.filter(p=>p.v).map(p=>[p.t,kW(p.v)]), top=Math.max(10,Math.ceil(Math.max(0,...ps.map(p=>p[1]))/10)*10);   // multiple of 10: the mid label stays a whole number that fits (27.5 kW was clipped)
  const L=44,R=10,Tp=8,B=22,pw=w-L-R,ph=h-Tp-B, X=t=>L+(t-t0)/1440*pw, Y=v=>Tp+ph-(v/top)*ph;
  g.font="11px "+css("--f-mono"); g.fillStyle=css("--muted"); g.strokeStyle=css("--line"); g.lineWidth=1;
  [0,top/2,top].forEach(v=>{ g.beginPath(); g.moveTo(L,Y(v)+.5); g.lineTo(L+pw,Y(v)+.5); g.stroke(); g.textAlign="right"; g.fillText(v+" kW",L-6,Y(v)+4); });
  g.textAlign="center"; for(let k=Math.ceil(t0/240)*240;k<=t1;k+=240){ if(k<0) continue; g.fillText(String(Math.floor(k%1440/60)).padStart(2,"0")+":00",X(k),h-6); }
  if(ps.length<2) return;
  const col=css("--elec"); g.strokeStyle=col; g.lineWidth=2; g.beginPath(); ps.forEach(([t,v],i)=>i?g.lineTo(X(t),Y(v)):g.moveTo(X(t),Y(v))); g.stroke();
  const [et,ev]=ps[ps.length-1]; g.fillStyle=col; g.beginPath(); g.arc(X(et),Y(ev),3.5,0,7); g.fill();
  g.textAlign="left"; g.fillText(`now ${ev.toFixed(1)} kW`,L+6,Tp+12);
}
$("legend").innerHTML=[...new Map(Object.entries(STAGES).map(([k,v])=>[nm(k),v]))].map(([k,v])=>`<span><i style="background:${v}"></i>${k}</span>`).join("");

let running=true,last=performance.now(),acc=0;
$("themeBtn").onclick=()=>{ const d=document.documentElement, l=d.dataset.theme!=="light"; l? d.dataset.theme="light": delete d.dataset.theme; try{ localStorage.setItem("theme",l?"light":"dark"); }catch(e){} drawTrend(); renderBend(); drawPlots(true); };
// Dataset export: one CSV row per recorded minute (S.hist, last 48 h), one column per sensor (plant column names).
function histCsv(){ const cols=[...IDX];
  const rows=[["minute","plant_stage",...cols.map(([c])=>c)].join(",")];
  S.hist.forEach(h=>{ if(h.v) rows.push([h.t,`"${h.st}"`,...cols.map(([,i])=>isNaN(h.v[i])?"":+h.v[i].toFixed(3))].join(",")); });
  return "﻿"+rows.join("\n"); }
$("saveBtn").onclick=()=>{ const a=document.createElement("a"); a.href=URL.createObjectURL(new Blob([histCsv()],{type:"text/csv"}));
  a.download=`sofc_twin_day${Math.floor(S.t/1440)+1}_${String(Math.floor(S.t%1440/60)).padStart(2,"0")}h.csv`; a.click(); setTimeout(()=>URL.revokeObjectURL(a.href),1000); };
$("play").onclick=()=>{ running=!running; $("play").textContent=running?"Pause":"Play"; last=performance.now(); };

// ---------- data viewer: a data file (2026-11-06) ----------
// Source "Data file": one CSV (or .csv.gz) with the twin's column names, e.g. this app's Save data file or
// 04_synthetic_data/datasets/twin_181d_85pct_4pl_1cs_4rp4h/sofc_twin_dataset.csv.gz, or a plant logger day file (YYYYMMDD.txt: tab, decimal comma, 1 Hz).
// One row per minute (first sample of each minute). The rows take the place of the simulated minutes, so the drawing,
// readings, plots, trends and Save data all show them; knobs, playbook and stage bar are locked meanwhile.
const KEEP_MIN=2880, DEC=new TextDecoder();
const COL=n=>IDX.get(n), FLOW=n=>COL(`ct_FIRC_${n}_PV_ProcessValue`), Z=x=>x===x?x:0;
const I_STACK=COL("T_stack_C"), I_EAPH=COL("EIRC_2_01_ActV_In_ThreePhasePower"), I_TIN=COL("TIRC_2_06"), TOT=["P_total_kW","I_total_A","V_total_V"].map(COL),
  ETA=["eta_module_pct",...[1,2,3,4,5].map(k=>`eta_string${k}_pct`)].map(COL);
const HEAT_I=["pi_IIR_5_1_3_ActVal","pi_IIR_3_1_1_ActVal"].map(COL);
// a row in the twin's state fields, so stage(), the flow lines and the knob read-outs work unchanged
function rowState(v){
  const cur=PW_IDX.map(([i])=>v[i]).filter(x=>x===x);
  return {air:Z(v[FLOW(111)])+Z(v[FLOW(112)]),pox:Z(v[FLOW(12)]),n2:Z(v[FLOW(13)]),h2:Z(v[FLOW(15)]),ng:Z(v[FLOW(14)]),
    I:cur.length?cur.reduce((a,b)=>a+b,0)/cur.length:0, Tin:v[I_TIN]===v[I_TIN]?v[I_TIN]:S.Tin,
    // shortcut: heaters on = EAPH > 0.2 kW (operating_states.py EAPH_ON_W) or ERH / EAGH current > 0.5 A; use a heater-enable tag if one is logged
    heaters:Z(v[I_EAPH])>0.2||HEAT_I.some(i=>Z(v[i])>0.5)};
}
// "2027-01-01 00:00" or logger "13.11.2025 00:00:01" → minutes, clock time kept as written (UTC maths, no time zone shift)
function tsMin(s){ s=(s||"").replace(/"/g,"").trim(); let m=s.match(/^(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d)/);
  if(m) return Date.UTC(+m[1],m[2]-1,+m[3],+m[4],+m[5])/6e4;
  m=s.match(/^(\d\d)\.(\d\d)\.(\d{4}) (\d\d):(\d\d)/); return m? Date.UTC(+m[3],m[2]-1,+m[1],+m[4],+m[5])/6e4: NaN; }
const clockOf=(t,day)=>t>=1e6? new Date(t*6e4).toISOString().slice(0,16).replace("T"," "): day;
const feedClock=day=>FEED.row? `${FEED.name} · ${clockOf(S.t,day)}`: "Loading…";
// Header line → column map; then each line → {t, T, dT, st, v} (null for the header, a blank or an already-seen minute).
function rowParser(){
  let sep, raw, map, tI, mI, sI, tc; const back=[];
  return line=>{
    line=line.replace(/\r$/,"");
    if(!map){
      line=line.replace(/^﻿/,""); sep=line.includes("\t")?"\t":","; raw=sep==="\t";
      const cols=line.split(sep).map(c=>c.trim().replace(/^"|"$/g,""));
      map=cols.map(c=>IDX.has(c)?IDX.get(c):-1); tI=cols.findIndex(c=>c==="timestamp"||c==="Date Time"); mI=cols.indexOf("minute"); sI=cols.indexOf("plant_stage");
      if(tI<0&&mI<0) throw new Error("no timestamp, Date Time or minute column in the first line");
      // logger files have no T_stack_C: median of the stack TCs; TIR_4_6_25 reads ambient on every day (stage_signals.py)
      tc=cols.map((c,i)=>/^TIR_4_6_\d+$/.test(c)&&c!=="TIR_4_6_25"?i:-1).filter(i=>i>=0);
      return null;
    }
    if(!line.trim()) return null;
    const a=line.split(sep), t=tI>=0? tsMin(a[tI]): +a[mI];
    if(!isFinite(t)||t<=FEED.lastT) return null;
    FEED.lastT=t;
    const num=s=>s? +(raw? s.replace(",","."): s): NaN, v=new Float32Array(ALLROWS.length).fill(NaN);
    for(let i=0;i<a.length;i++){ const k=map[i]; if(k<0) continue; const x=num(a[i]); if(x===x&&!(raw&&x===-1)) v[k]=x; }   // -1 = logger fill value
    if(raw&&v[I_EAPH]===v[I_EAPH]) v[I_EAPH]/=1000;                                                                      // logger W → kW (tools/prep.py)
    if(v[I_STACK]!==v[I_STACK]&&tc.length){ const T=tc.map(i=>num(a[i])).filter(x=>x>0&&x<1000).sort((p,q)=>p-q), n=T.length;
      if(n) v[I_STACK]=n%2? T[n>>1]: (T[n/2-1]+T[n/2])/2; }
    if(v[TOT[0]]!==v[TOT[0]]){ const p=PW_IDX.reduce((s,[i,u])=>s+Z(v[i])*Z(v[u]),0), I=PW_IDX.reduce((s,[i])=>s+Z(v[i]),0);
      v[TOT[0]]=p/1000; v[TOT[1]]=I; v[TOT[2]]=I>0? p/I: PW_IDX.reduce((s,[,u])=>s+Z(v[u]),0)/5; }
    if(v[ETA[0]]!==v[ETA[0]]){ const ng=v[FLOW(14)];
      v[ETA[0]]=eta(Z(v[TOT[0]]),ng)??NaN; PW_IDX.forEach(([i,u],k)=>v[ETA[k+1]]=eta(Z(v[i])*Z(v[u])/1000,ng,5)??NaN); }
    const T=v[I_STACK]; back.push(T); if(back.length>11) back.shift();
    const dT=back.length>1&&T===T&&back[0]===back[0]? (T-back[0])*60/(back.length-1): 0;   // °C/h over the last 10 rows
    // stage: the file's plant_stage, else the twin's own stage rules on the row (no trip purge: trips are not in the row)
    const st=sI>=0&&a[sI]? a[sI].replace(/"/g,"").trim(): stage({...rowState(v),T:Z(T),slope:dT,trip:0});
    return {t,T:Z(T),dT,st,v};
  };
}
function eachLine(buf,onLine){ let s=0; for(let i;(i=buf.indexOf(10,s))>=0;s=i+1) onLine(DEC.decode(buf.subarray(s,i))); return s; }   // → bytes used up
async function readFile(f,onLine){
  let st=f.stream(); if(/\.gz$/i.test(f.name)) st=st.pipeThrough(new DecompressionStream("gzip"));
  const rd=st.getReader(); let carry=new Uint8Array(0);
  for(let r;!(r=await rd.read()).done;){ const b=new Uint8Array(carry.length+r.value.length); b.set(carry); b.set(r.value,carry.length); carry=b.slice(eachLine(b,onLine)); }
  if(carry.length) onLine(DEC.decode(carry));
}
// show row i (1-based): the last 48 h up to it become the history, the row becomes the plant state
function show(i){
  const rows=FEED.rows; if(!rows.length) return;
  FEED.i=i=Math.max(1,Math.min(rows.length,i));
  const r=rows[i-1]; S.hist=rows.slice(Math.max(0,i-KEEP_MIN),i); FEED.row=r.v;
  Object.assign(S,rowState(r.v),{t:r.t,T:r.T,dT:r.dT,slope:r.dT,feedSt:r.st||"Shutdown",trip:0,estop:false});
  if(S.border&&S.border.t>S.t) S.border=null;
  noteBorder(S); $("seek").value=i;
}
const lock=on=>[document.querySelector(".ctl"),$("stages"),$("startBtn")].forEach(e=>e.inert=on);
function enterFeed(mode){
  if(FEED.mode==="twin") FEED.snap={...S};
  Object.assign(FEED,{mode,rows:[],i:0,row:null,lastT:-Infinity,ready:false});
  S.border=null; $("source").value=mode; $("seek").hidden=false; lock(true); render();
}
function leaveFeed(){
  if(FEED.mode==="twin") return;
  Object.assign(FEED,{mode:"twin",rows:[],row:null,ready:false});
  Object.assign(S,FEED.snap,{feedSt:null}); snapSensors();
  $("source").value="twin"; $("seek").hidden=true; lock(false); render();
}
async function loadFile(f){
  enterFeed("file"); FEED.name=f.name;
  const parse=rowParser(), rows=FEED.rows;
  await readFile(f,line=>{ const r=parse(line); if(r&&rows.push(r)%20000===0) $("clock").textContent=`Loading ${f.name} · ${rows.length} min`; });
  if(!rows.length) throw new Error("no rows with a time");
  $("seek").max=rows.length; FEED.ready=true; show(1); render();
}
$("source").onchange=e=>{
  const m=e.target.value; e.target.value=FEED.mode;    // stays on the old source until the new one is open (a cancel changes nothing)
  if(m==="twin") return leaveFeed();
  $("fileIn").click();
};
$("fileIn").onchange=async e=>{ const f=e.target.files[0]; e.target.value=""; if(!f) return;
  try{ await loadFile(f); }catch(err){ leaveFeed(); alert(`Could not read ${f.name}: ${err.message}`); } };
$("seek").oninput=e=>{ show(+e.target.value); render(); };

function loop(now){ const dt=(now-last)/1000; last=now;
  if(running&&(FEED.mode==="twin"||FEED.ready)){ acc+=dt*(+$("speed").value); const n=Math.floor(acc);
    if(n>0){ acc-=n;
      if(FEED.mode==="twin") tick(Math.min(n,120));
      else { show(FEED.i+n); if(FEED.i>=FEED.rows.length){ running=false; $("play").textContent="Play"; } }   // end of the file: pause
      render(); } }
  requestAnimationFrame(loop); }
window.addEventListener("resize",()=>{ drawTrend(); renderBend(); drawPlots(true); });

playMsg="Plant in shutdown: stack at room temperature, air off. Press Start plant to begin the cold start.";
select("stack"); render(); requestAnimationFrame(loop);
})();
