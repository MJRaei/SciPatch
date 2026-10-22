#!/bin/bash
# run GPAW scf jobs two at a time; record run ids
SP=$1; J=$2
python3 -c "import json;[print(j['name'],j['structure'],j['kd']) for j in json.load(open('$J'))]" | while read n s kd; do
  while [ $(pgrep -f "envs/gpaw/bin/python" | wc -l) -ge 2 ]; do sleep 10; done
  scipatch run gpaw scf --args "{\"structure\":\"$s\",\"xc\":\"PBE\",\"ecut_ev\":450,\"kpoint_density\":$kd,\"output\":\"$SP/dft/$n.gpw\"}" --background --json | python3 -c "import json,sys;d=json.load(sys.stdin);print('$n',d.get('run_id'),d.get('status'),flush=True)"
  sleep 5
done
echo DFT LAUNCHED
