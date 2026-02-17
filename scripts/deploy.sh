#!/usr/bin/env bash
set -e

# House
# HOST="root@192.168.103.184"
# Office
HOST="root@192.168.1.106"
COMPONENT="cala"
DEST="/config/custom_components"

echo "🧹 Removing old component..."
ssh $HOST "rm -rf $DEST/$COMPONENT"

echo "📦 Copying new component..."
scp -r ../custom_components/$COMPONENT $HOST:$DEST/

echo "🔄 Restarting Home Assistant..."
ssh $HOST "ha core restart"

echo "✅ Deploy complete"