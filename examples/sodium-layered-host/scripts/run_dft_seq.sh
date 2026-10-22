#!/bin/bash
SP=$1; J=$2
python3 -c "import json;[print(j['name'],j['structure'],j['kd']) for j in json.load(open('$J'))]" | while read n s kd; do
  rid=$(scipatch run gpaw scf --args "{\"structure\":\"$s\",\"xc\":\"PBE\",\"ecut_ev\":400,\"kpoint_density\":$kd,\"output\":\"$SP/dft/$n.gpw\"}" --background --json | python3 -c "import json,sys;print(json.load(sys.stdin)['run_id'])")
  echo "$n $rid"
  while [ "$(scipatch runs show $rid --json | python3 -c 'import json,sys;print(json.load(sys.stdin)["status"])')" = "running" ]; do sleep 20; done
  echo "$n finished"
done
echo DFT ALL DONE
