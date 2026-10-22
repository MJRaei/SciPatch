#!/bin/bash
# Sequential pipeline: NEB (one at a time) in parallel with MD (one at a time).
export OMP_NUM_THREADS=3 MKL_NUM_THREADS=3 OPENBLAS_NUM_THREADS=3 VECLIB_MAXIMUM_THREADS=3
PY=~/.scipatch/envs/ml-potentials/bin/python
cd /private/tmp/claude-501/-Users-mjraei/e145cffd-d223-4597-bc8b-5cef3f6d1863/scratchpad/neb
(
 while pgrep -f "neb_na.py /private/tmp/claude-501/-Users-mjraei/e145cffd-d223-4597-bc8b-5cef3f6d1863/scratchpad ZrS2 orb" > /dev/null; do sleep 10; done
 for job in "ZrS2 chgnet vac,dil" "ZrS2 mace vac,dil" "ZrS2 tensornet vac,dil" "TiS2 orb vac,dil" "HfS2 orb vac" "ZrSe2 orb vac"; do
   set -- $job; $PY -I /private/tmp/claude-501/-Users-mjraei/e145cffd-d223-4597-bc8b-5cef3f6d1863/scratchpad/scripts/neb_na.py /private/tmp/claude-501/-Users-mjraei/e145cffd-d223-4597-bc8b-5cef3f6d1863/scratchpad $1 $2 $3 2>&1 | grep -v -i warn
 done; echo NEB ALL DONE
) > /private/tmp/claude-501/-Users-mjraei/e145cffd-d223-4597-bc8b-5cef3f6d1863/scratchpad/neb/neb2.log 2>&1 &
(
 for T in 1100 900 1300; do
   rid=$(scipatch run ml-potentials molecular_dynamics --args "{\"structure\":\"/private/tmp/claude-501/-Users-mjraei/e145cffd-d223-4597-bc8b-5cef3f6d1863/scratchpad/md/ZrS2_Na0.5_tensornet_relaxed.cif\",\"model\":\"TensorNet-MatPES-PBE-2025.2\",\"temperature_k\":$T,\"steps\":6000,\"timestep_fs\":2,\"seed\":2,\"trajectory\":\"/private/tmp/claude-501/-Users-mjraei/e145cffd-d223-4597-bc8b-5cef3f6d1863/scratchpad/md/ZrS2_tn_${T}K.traj\"}" --background --json | python3 -c "import json,sys;print(json.load(sys.stdin)['run_id'])")
   echo "$T $rid"
   while [ "$(scipatch runs show $rid --json | python3 -c 'import json,sys;print(json.load(sys.stdin)["status"])')" = "running" ]; do sleep 20; done
   echo "$T done"
 done; echo MD ALL DONE
) > /private/tmp/claude-501/-Users-mjraei/e145cffd-d223-4597-bc8b-5cef3f6d1863/scratchpad/md/md2.log 2>&1 &
wait
