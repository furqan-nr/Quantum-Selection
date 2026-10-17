#!/bin/bash
# usage: slice.sh <venv> <rundir> <outfile>
V=$1; R=$2; O=$3
cd $R
for f in $(find test/python/transpiler test/python/compiler -name 'test_*.py' | sort); do
  grep -q "^$f " $O 2>/dev/null && continue
  S=$(date +%s.%N)
  res=$(timeout 600 $V/bin/python -m pytest -q -p no:cacheprovider --no-header "$f" 2>&1 | tail -1)
  rc=$?
  E=$(date +%s.%N)
  echo "$f | $(echo "$E-$S"|bc) | $res" >> $O
done
echo DONE >> $O
