"""Efficiency check for the SOFC POC data (2026-11-04).
No efficiency tag is logged. This computes:
  gross electrical efficiency = DC power (sum V x I of 5 strings) / fuel energy (PLC_pv_rM_CH4 kg/h x LHV)
  fuel utilisation            = current x 476 cells / (8 F x CH4 mol/s)   -> compared with PLC_pv_rFU_Worst_1..5
  after-heater efficiency     = (DC power - heater power) / fuel energy  (heater IIR current x 230 V assumed + EAPH power)
  string efficiency           = string V x I / (fuel energy / 5)  -- one gas meter only, so each string is given 1/5 of the gas
                                (same split as the PLC rFU_Worst tags): ranks the strings, not a measured per-string value
Blower / inverter power is not logged.
"""
import pandas as pd, glob, numpy as np, pyarrow.parquet as pq, sys
OUT = sys.argv[1] if len(sys.argv) > 1 else "efficiency_rows.csv"
# PLC monitor columns: the EIRC_4X_* ones shift to wrong data from 2026-03-20 ~11:00 (see operating_states.py)
V=[f"PLC_hostSetp_ctrl_ctEIRC4{i}_rVoltMonitor" for i in range(1,6)]; I=[f"PLC_hostSetp_ctrl_ctEIRC4{i}_rCurrMonitor" for i in range(1,6)]
W=[f"PLC_pv_rFU_Worst_{i}" for i in range(1,6)]
H=["pi_IIR_3_1_1_ActVal","pi_IIR_5_1_1_ActVal","pi_IIR_5_1_2_ActVal","pi_IIR_5_1_3_ActVal","pi_IIR_6_1_1_ActVal"]
E=["pi_EIRC_2_01_ActV_rMas_Power_[W]","pi_EIRC_2_01_ActV_rSlv1_Power_[W]","pi_EIRC_2_01_ActV_rSlv2_Power_[W]"]
TV=[f"TotalVoltage_M{i}" for i in range(1,6)]
cols=V+I+W+H+E+TV+["ct_FIRC_14_PV_ProcessValue","PLC_pv_rM_CH4"]
LHV=50.0; F=96485; NCELL=4*119
fr=[]
for f in sorted(glob.glob("02_data/parquet/*.parquet")):
    names=pq.read_schema(f).names
    if not all(c in names for c in V+I): continue
    d=pd.read_parquet(f,columns=[c for c in cols if c in names])
    d=d.apply(pd.to_numeric,errors="coerce"); d["file"]=f[-16:-8]; fr.append(d)
d=pd.concat(fr,ignore_index=True)
d["P"]=sum(d[v]*d[i] for v,i in zip(V,I))/1000
on=d[(d.P>3)&(d.PLC_pv_rM_CH4>1)].copy()
on["fuel_kW"]=on.PLC_pv_rM_CH4/3600*LHV*1000
on["eta"]=on.P/on.fuel_kW*100
nCH4=on.PLC_pv_rM_CH4/3600*1000/16.04
on["FU_calc"]=on[I].sum(axis=1)*NCELL/(8*F*nCH4)*100
on["heat_kW"]=on[[c for c in H if c in on]].fillna(0).sum(axis=1)*230/1000+on[[c for c in E if c in on]].fillna(0).sum(axis=1)/1000
on["eta_net"]=(on.P-on.heat_kW)/on.fuel_kW*100
ETA=[f"eta_s{k+1}" for k in range(5)]
for k in range(5): on[ETA[k]]=on[V[k]]*on[I[k]]/1000/(on.fuel_kW/5)*100
on["Vcell"]=on[TV].median(axis=1)/NCELL
print("rows (1 s each):",len(on))
print(on.groupby(pd.cut(on.P,[3,10,15,20,25,30,35])).agg(n=("P","size"),eta=("eta","median"),eta_net=("eta_net","median"),heat=("heat_kW","median"),FU=("FU_calc","median"),FU_tag=(W[0],"median"),fuel=("fuel_kW","median"),Vcell=("Vcell","median")).round(2))
print(on.groupby("file").agg(n=("P","size"),P=("P","median"),Pmax=("P","max"),eta=("eta","median"),eta_max=("eta","max"),FU=("FU_calc","median")).round(1))
for k in range(5):
    fu=on[I[k]]*NCELL/(8*F*nCH4/5)*100
    print(f"string {k+1}: FU calc {fu.median():.1f}  tag {on[W[k]].median():.1f}  r={fu.corr(on[W[k]]):.3f}  tag/calc={(on[W[k]]/fu).median():.3f}")
print("string efficiency % (gas split 1/5 each) by power band:")
print(on.groupby(pd.cut(on.P,[3,10,15,20,25,30,35]))[ETA].median().round(1))
print("heater parts median kW:", (on[H].median()*230/1000).round(2).to_dict(), (on[E].median()/1000).round(2).to_dict())
on[["file","P","fuel_kW","eta","eta_net","heat_kW","FU_calc"]+W+ETA+["Vcell"]].to_csv(OUT,index=False)
