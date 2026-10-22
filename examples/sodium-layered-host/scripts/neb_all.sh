#!/bin/bash
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 VECLIB_MAXIMUM_THREADS=2
PY=~/.scipatch/envs/ml-potentials/bin/python
cd /private/tmp/claude-501/-Users-mjraei/e145cffd-d223-4597-bc8b-5cef3f6d1863/scratchpad/neb
for job in "ZrS2 orb vac,dil" "ZrS2 chgnet vac,dil" "TiS2 orb vac,dil" "ZrS2 mace vac,dil" "ZrS2 tensornet vac,dil" "TiS2 chgnet vac,dil" "HfS2 orb vac" "ZrSe2 orb vac" "HfS2 chgnet vac" "ZrSe2 chgnet vac"; do
  set -- $job
  $PY -I /private/tmp/claude-501/-Users-mjraei/e145cffd-d223-4597-bc8b-5cef3f6d1863/scratchpad/scripts/neb_na.py /private/tmp/claude-501/-Users-mjraei/e145cffd-d223-4597-bc8b-5cef3f6d1863/scratchpad $1 $2 $3 2>&1 | grep -v -i warn
done
echo NEB ALL DONE
