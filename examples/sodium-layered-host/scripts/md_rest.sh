#!/bin/bash
st() { scipatch runs show $1 --json | python3 -c 'import json,sys;print(json.load(sys.stdin)["status"])'; }
while [ "$(st 20261022-134315-08cffa)" = "running" ]; do sleep 20; done
echo "1100 done"
ids=""
for T in 900 1300; do
  rid=$(scipatch run ml-potentials molecular_dynamics --args "{\"structure\":\"/private/tmp/claude-501/-Users-mjraei/e145cffd-d223-4597-bc8b-5cef3f6d1863/scratchpad/md/ZrS2_Na0.5_tensornet_relaxed.cif\",\"model\":\"TensorNet-MatPES-PBE-2025.2\",\"temperature_k\":$T,\"steps\":3000,\"timestep_fs\":2,\"seed\":3,\"trajectory\":\"/private/tmp/claude-501/-Users-mjraei/e145cffd-d223-4597-bc8b-5cef3f6d1863/scratchpad/md/ZrS2_tn_${T}K_short.traj\"}" --background --json | python3 -c "import json,sys;print(json.load(sys.stdin)['run_id'])")
  echo "$T $rid"; ids="$ids $rid"
done
for r in $ids; do while [ "$(st $r)" = "running" ]; do sleep 20; done; done
echo MD REST DONE
