#!/usr/bin/env bash

if [ ! -d /opt/openstreetmap-carto ]; then
  echo "/opt/openstreetmap-carto does not exist.  Run install.sh!"
  exit 1
fi

set -x

# Use D.C. to initialized DB because it is so small.
DC_MAP=district-of-columbia-221105.osm.pbf
wget --continue https://download.geofabrik.de/north-america/us/${DC_MAP} -O /tmp/${DC_MAP} || :

cd /opt/openstreetmap-carto || exit 2

# Initialize indexes and global polygons.   This may take multiple tries.
MAX_TRIES=3
COUNT=0
SUCCESS=false
external_data=false
dc_import=false
indexes=false
while [ "${COUNT}" -lt "${MAX_TRIES}" ]; do
  [[ "${external_data}" = false ]] &&
    sudo -u wrolpi nice -n 18 /opt/openstreetmap-carto/scripts/get-external-data.py \
      -C \
      -d gis -U wrolpi &&
    external_data=true
  [[ "${dc_import}" = false ]] &&
    sudo -u wrolpi nice -n 18 /opt/wrolpi/scripts/import_map.sh /tmp/${DC_MAP} &&
    dc_import=true
  [[ "${indexes}" = false ]] &&
    sudo -u wrolpi psql -d gis -f /opt/openstreetmap-carto/indexes.sql &&
    indexes=true
  if [[ "${external_data}" == true && "${dc_import}" == true && "${indexes}" == true ]]; then
    SUCCESS=true
    break
  fi
  ((COUNT = COUNT + 1))
done

if [[ "${SUCCESS}" == false ]]; then
  echo "Could not initialize map data.  Try running reset_map.sh, or install.sh."
  exit 3
fi

echo "Map has successfully been initialized"
